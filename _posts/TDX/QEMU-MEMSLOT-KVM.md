## Managing guest VM memory in KVM side 
### Generate memslots for gpa->hva mapping for KVM module 
To handle guest VM's memory, KVM module needs memslot providing information 
about GPA to HVA mapping. This helps KVM module translate GPA to HVA to HPA, 
usually when the page fault happens in the guest VM side. If there is no memslot
matching with the GPA, KVM cannot translate the GPA to HPA, which prevents the 
memory mapping for EPT. 

QEMU talks to KVM module through the KVM_SET_USER_MEMORY_REGION ioctl. The main 
role of this ioctl is generating the memslots using the provided information. 

\XXX{how the GPA and GVA mapping is generated should be illustrated very clearly}

```cpp
static long kvm_vm_ioctl(struct file *filp,
                           unsigned int ioctl, unsigned long arg)
{
        case KVM_SET_USER_MEMORY_REGION: {
                struct kvm_user_mem_region mem;
                unsigned long size;
                u32 flags;
                        
                memset(&mem, 0, sizeof(mem));
                
                r = -EFAULT;
                
                if (get_user(flags,
                        (u32 __user *)(argp + offsetof(typeof(mem), flags))))
                        goto out;

                if (flags & KVM_MEM_PRIVATE)
                        size = sizeof(struct kvm_userspace_memory_region_ext);
                else 
                        size = sizeof(struct kvm_userspace_memory_region);
        
                if (copy_from_user(&mem, argp, size))
                        goto out;

                r = -EINVAL;
                if ((flags ^ mem.flags) & KVM_MEM_PRIVATE)
                        goto out;

                r = kvm_vm_ioctl_set_memory_region(kvm, &mem);
                break;

```

```cpp
static int kvm_vm_ioctl_set_memory_region(struct kvm *kvm,
                                          struct kvm_user_mem_region *mem)
{       
        if ((u16)mem->slot >= KVM_USER_MEM_SLOTS)
                return -EINVAL;
                           
        return kvm_set_memory_region(kvm, mem);
        }              
```

```cpp
/* Internal helper, the layout must match above user visible structures */
struct kvm_user_mem_region {
        __u32 slot;
        __u32 flags;
        __u64 guest_phys_addr;
        __u64 memory_size;
        __u64 userspace_addr;
        __u64 private_offset;
        __u32 private_fd;
        __u32 pad1;
        __u64 pad2[14];
};
```

To allow KVM module to generate memslot meta-data, QEMU should provide proper
information. QEMU passes the GPA (guest_phys_addr) and HVA (userspace_addr) 
mapped to the GPA together to the KVM module so that the KVM can translate GPA 
to HPA (e.g., when the page fault happens). 

```cpp
/*      
 * Allocate some memory and give it an address in the guest physical address
 * space. 
 *      
 * Discontiguous memory is allowed, mostly for framebuffers.
 *              
 * Must be called holding kvm->slots_lock for write.
 */     
int __kvm_set_memory_region(struct kvm *kvm,
                            const struct kvm_user_mem_region *mem)
{       
        struct kvm_memory_slot *old, *new;
        struct kvm_memslots *slots;
        enum kvm_mr_change change;
        unsigned long npages;
        gfn_t base_gfn;
        int as_id, id;  
        int r;

        r = check_memory_region_flags(kvm, mem);
        if (r)
                return r;

        as_id = mem->slot >> 16;
        id = (u16)mem->slot;

        /* General sanity checks */
        if ((mem->memory_size & (PAGE_SIZE - 1)) ||
            (mem->memory_size != (unsigned long)mem->memory_size))
                return -EINVAL;
        if (mem->guest_phys_addr & (PAGE_SIZE - 1))
                return -EINVAL;
        /* We can read the guest memory with __xxx_user() later on. */
        if ((mem->userspace_addr & (PAGE_SIZE - 1)) ||
            (mem->userspace_addr != untagged_addr(mem->userspace_addr)) ||
             !access_ok((void __user *)(unsigned long)mem->userspace_addr,
                        mem->memory_size))
                return -EINVAL;
        if (mem->flags & KVM_MEM_PRIVATE &&
                (mem->private_offset & (PAGE_SIZE - 1) ||
                 mem->private_offset > U64_MAX - mem->memory_size))
                return -EINVAL;
        if (as_id >= KVM_ADDRESS_SPACE_NUM || id >= KVM_MEM_SLOTS_NUM)
                return -EINVAL;
        if (mem->guest_phys_addr + mem->memory_size < mem->guest_phys_addr)
                return -EINVAL;
        if ((mem->memory_size >> PAGE_SHIFT) > KVM_MEM_MAX_NR_PAGES)
                return -EINVAL;

        slots = __kvm_memslots(kvm, as_id);

        /*
         * Note, the old memslot (and the pointer itself!) may be invalidated
         * and/or destroyed by kvm_set_memslot().
         */
        old = id_to_memslot(slots, id);

        if (!mem->memory_size) {
                if (!old || !old->npages)
                        return -EINVAL;

                if (WARN_ON_ONCE(kvm->nr_memslot_pages < old->npages))
                        return -EIO;

                return kvm_set_memslot(kvm, old, NULL, KVM_MR_DELETE);
        }

        base_gfn = (mem->guest_phys_addr >> PAGE_SHIFT);
        npages = (mem->memory_size >> PAGE_SHIFT);

        if (!old || !old->npages) {
                change = KVM_MR_CREATE;

                /*
                 * To simplify KVM internals, the total number of pages across
                 * all memslots must fit in an unsigned long.
                 */
                if ((kvm->nr_memslot_pages + npages) < kvm->nr_memslot_pages)
                        return -EINVAL;
        } else { /* Modify an existing slot. */
                /* Private memslots are immutable, they can only be deleted. */
                if (mem->flags & KVM_MEM_PRIVATE)
                        return -EINVAL;
                if ((mem->userspace_addr != old->userspace_addr) ||
                    (npages != old->npages) ||
                    ((mem->flags ^ old->flags) & KVM_MEM_READONLY))
                        return -EINVAL;

                if (base_gfn != old->base_gfn)
                        change = KVM_MR_MOVE;
                else if (mem->flags != old->flags)
                        change = KVM_MR_FLAGS_ONLY;
                else /* Nothing to change. */
                        return 0;
        }

        if ((change == KVM_MR_CREATE || change == KVM_MR_MOVE) &&
            kvm_check_memslot_overlap(slots, id, base_gfn, base_gfn + npages))
                return -EEXIST;

        /* Allocate a slot that will persist in the memslot. */
        new = kzalloc(sizeof(*new), GFP_KERNEL_ACCOUNT);
        if (!new)
                return -ENOMEM;

        new->as_id = as_id;
        new->id = id;
        new->base_gfn = base_gfn;
        new->npages = npages;
        new->flags = mem->flags;
        new->userspace_addr = mem->userspace_addr;
        if (mem->flags & KVM_MEM_PRIVATE) {
                new->private_file = fget(mem->private_fd);
                if (!new->private_file) {
                        r = -EBADF;
                        goto out;
                }
                /* TODO: Check if file is kvm memslot compatible. */
                new->private_offset = mem->private_offset;
        }

        new->kvm = kvm;

        r = kvm_set_memslot(kvm, old, new, change);
        if (r)
                goto out;

        return 0

out:
        if (new->private_file)
                fput(new->private_file);
        kfree(new);
        return r;
}
```

The **__kvm_set_memory_region** function generates memslot used for this 
translation later by the KVM module. 

```cpp
/*      
 * KVM_SET_USER_MEMORY_REGION ioctl allows the following operations:
 * - create a new memory slot
 * - delete an existing memory slot
 * - modify an existing memory slot
 *   -- move it in the guest physical memory space
 *   -- just change its flags
 *
 * Since flags can be changed by some of these operations, the following
 * differentiation is the best we can do for __kvm_set_memory_region():
 */             
enum kvm_mr_change {
        KVM_MR_CREATE,
        KVM_MR_DELETE,
        KVM_MR_MOVE,
        KVM_MR_FLAGS_ONLY, 
};              
```

Based on the type of KVM_SET_USER_MEMORY_REGION operation, the required 
operation to manage memslot is determined. If it requires the memslot to be 
updated, it retrieves/generates old/new memslots. To update the memslot info,
it invokes kvm_set_memslot function.


### Update memslot information 
```cpp
static int kvm_set_memslot(struct kvm *kvm,
                           struct kvm_memory_slot *old,
                           struct kvm_memory_slot *new,
                           enum kvm_mr_change change)
{
        struct kvm_memory_slot *invalid_slot;
        int r;

        /*
         * Released in kvm_swap_active_memslots.
         *
         * Must be held from before the current memslots are copied until
         * after the new memslots are installed with rcu_assign_pointer,
         * then released before the synchronize srcu in kvm_swap_active_memslots.
         *
         * When modifying memslots outside of the slots_lock, must be held
         * before reading the pointer to the current memslots until after all
         * changes to those memslots are complete.
         *
         * These rules ensure that installing new memslots does not lose
         * changes made to the previous memslots.
         */
        mutex_lock(&kvm->slots_arch_lock);

        /*
         * Invalidate the old slot if it's being deleted or moved.  This is
         * done prior to actually deleting/moving the memslot to allow vCPUs to
         * continue running by ensuring there are no mappings or shadow pages
         * for the memslot when it is deleted/moved.  Without pre-invalidation
         * (and without a lock), a window would exist between effecting the
         * delete/move and committing the changes in arch code where KVM or a
         * guest could access a non-existent memslot.
         *
         * Modifications are done on a temporary, unreachable slot.  The old
         * slot needs to be preserved in case a later step fails and the
         * invalidation needs to be reverted.
         */
        if (change == KVM_MR_DELETE || change == KVM_MR_MOVE) {
                invalid_slot = kzalloc(sizeof(*invalid_slot), GFP_KERNEL_ACCOUNT);
                if (!invalid_slot) {
                        mutex_unlock(&kvm->slots_arch_lock);
                        return -ENOMEM;
                }
                kvm_invalidate_memslot(kvm, old, invalid_slot);
        }

        r = kvm_prepare_memory_region(kvm, old, new, change);
        if (r) {
                /*
                 * For DELETE/MOVE, revert the above INVALID change.  No
                 * modifications required since the original slot was preserved
                 * in the inactive slots.  Changing the active memslots also
                 * release slots_arch_lock.
                 */
                if (change == KVM_MR_DELETE || change == KVM_MR_MOVE) {
                        kvm_activate_memslot(kvm, invalid_slot, old);
                        kfree(invalid_slot);
                } else {
                        mutex_unlock(&kvm->slots_arch_lock);
                }
                return r;
        }

        /*
         * For DELETE and MOVE, the working slot is now active as the INVALID
         * version of the old slot.  MOVE is particularly special as it reuses
         * the old slot and returns a copy of the old slot (in working_slot).
         * For CREATE, there is no old slot.  For DELETE and FLAGS_ONLY, the
         * old slot is detached but otherwise preserved.
         */
        if (change == KVM_MR_CREATE)
                kvm_create_memslot(kvm, new);
        else if (change == KVM_MR_DELETE)
                kvm_delete_memslot(kvm, old, invalid_slot);
        else if (change == KVM_MR_MOVE)
                kvm_move_memslot(kvm, old, new, invalid_slot);
        else if (change == KVM_MR_FLAGS_ONLY)
                kvm_update_flags_memslot(kvm, old, new);
        else
                BUG();

        /* Free the temporary INVALID slot used for DELETE and MOVE. */
        if (change == KVM_MR_DELETE || change == KVM_MR_MOVE)
                kfree(invalid_slot);

        /*
         * No need to refresh new->arch, changes after dropping slots_arch_lock
         * will directly hit the final, active memslot.  Architectures are
         * responsible for knowing that new->arch may be stale.
         */
        kvm_commit_memory_region(kvm, old, new, change);

        return 0;
}
```

Based on the change types, different operations will update memslot properly.

### For TDX
>Extend the memslot definition to provide guest private memory through a
file descriptor(fd) instead of userspace_addr(hva). Such guest private
memory(fd) may never be mapped into userspace so no userspace_addr(hva)
can be used. Instead add another two new fields
(private_fd/private_offset), plus the existing memory_size to represent
the private memory range. Such memslot can still have the existing
userspace_addr(hva). When use, a single memslot can maintain both
private memory through private fd(private_fd/private_offset) and shared
memory through hva(userspace_addr). A GPA is considered private by KVM
if the memslot has private fd and that corresponding page in the private
fd is populated, otherwise, it's shared.
>
Since there is no userspace mapping for private fd so we cannot
rely on get_user_pages() to get the pfn in KVM, instead we add a new
memfile_notifier in the memslot and rely on it to get pfn by interacting
its callbacks from memory backing store with the fd/offset.
>
This new extension is indicated by a new flag KVM_MEM_PRIVATE. At
compile time, a new config HAVE_KVM_PRIVATE_MEM is added and right now
it is selected on X86_64 for Intel TDX usage.
>
To make KVM easy, internally we use a binary compatible struct
kvm_user_mem_region to handle both the normal and the '_ext' variants.





\XXX{Don't know when the page_attr information is used}
### Prepare memory region for guest VM 
```cpp
static int kvm_prepare_memory_region(struct kvm *kvm,
                                     const struct kvm_memory_slot *old,
                                     struct kvm_memory_slot *new,
                                     enum kvm_mr_change change)
{
        int r;

        if (change == KVM_MR_CREATE && new->flags & KVM_MEM_PRIVATE) {
                r = kvm_private_mem_register(new);
                if (r)
                        return r;
        }

        /*
         * If dirty logging is disabled, nullify the bitmap; the old bitmap
         * will be freed on "commit".  If logging is enabled in both old and
         * new, reuse the existing bitmap.  If logging is enabled only in the
         * new and KVM isn't using a ring buffer, allocate and initialize a
         * new bitmap.
         */
        if (change != KVM_MR_DELETE) {
                if (!(new->flags & KVM_MEM_LOG_DIRTY_PAGES))
                        new->dirty_bitmap = NULL;
                else if (old && old->dirty_bitmap)
                        new->dirty_bitmap = old->dirty_bitmap;
                else if (!kvm->dirty_ring_size) {
                        r = kvm_alloc_dirty_bitmap(new);
                        if (r)
                                return r;

                        if (kvm_dirty_log_manual_protect_and_init_set(kvm))
                                bitmap_set(new->dirty_bitmap, 0, new->npages);
                }
        }

        r = kvm_arch_prepare_memory_region(kvm, old, new, change);

        /* Free the bitmap on failure if it was allocated above. */
        if (r && new && new->dirty_bitmap && (!old || !old->dirty_bitmap))
                kvm_destroy_dirty_bitmap(new);

        if (r && change == KVM_MR_CREATE && new->flags & KVM_MEM_PRIVATE)
            kvm_private_mem_unregister(new);

        return r;
}
```

```cpp
int kvm_arch_prepare_memory_region(struct kvm *kvm,
                                   const struct kvm_memory_slot *old,
                                   struct kvm_memory_slot *new,
                                   enum kvm_mr_change change)
{
        if (change == KVM_MR_CREATE || change == KVM_MR_MOVE) {
                if ((new->base_gfn + new->npages - 1) > kvm_mmu_max_gfn())
                        return -EINVAL;

                return kvm_alloc_memslot_metadata(kvm, new);
        }

        if (change == KVM_MR_FLAGS_ONLY)
                memcpy(&new->arch, &old->arch, sizeof(old->arch));
        else if (WARN_ON_ONCE(change != KVM_MR_DELETE))
                return -EIO;

        return 0;
}
```

```cpp
static int kvm_alloc_memslot_metadata(struct kvm *kvm,
                                      struct kvm_memory_slot *slot)
{
        unsigned long npages = slot->npages;
        int i, r;

        /*
         * Clear out the previous array pointers for the KVM_MR_MOVE case.  The
         * old arrays will be freed by __kvm_set_memory_region() if installing
         * the new memslot is successful.
         */
        memset(&slot->arch, 0, sizeof(slot->arch));

        if (kvm_memslots_have_rmaps(kvm)) {
                r = memslot_rmap_alloc(slot, npages);
                if (r)
                        return r;
        }

        for (i = 0; i < KVM_NR_PAGE_SIZES; ++i) {
                struct kvm_page_attr *page_attr;
                struct kvm_lpage_info *linfo;
                unsigned long ugfn, j;
                int lpages;
                int level = i + 1;

                lpages = __kvm_mmu_slot_lpages(slot, npages, level);

                page_attr = __vcalloc(lpages, sizeof(*page_attr), GFP_KERNEL_ACCOUNT);
                if (!page_attr)
                        goto out_free;
                slot->arch.page_attr[i] = page_attr;

                for (j = 0; j < lpages; j++)
                        page_attr[j].type = KVM_PAGE_TYPE_PRIVATE;

                if (i == 0)
                        continue;

                linfo = __vcalloc(lpages, sizeof(*linfo), GFP_KERNEL_ACCOUNT);
                if (!linfo)
                        goto out_free;

                slot->arch.lpage_info[i - 1] = linfo;

                if (slot->base_gfn & (KVM_PAGES_PER_HPAGE(level) - 1)) {
                        page_attr[0].type = KVM_PAGE_TYPE_INVALID;
                        linfo[0].disallow_lpage = 1;
                }
                if ((slot->base_gfn + npages) & (KVM_PAGES_PER_HPAGE(level) - 1)) {
                        page_attr[lpages - 1].type = KVM_PAGE_TYPE_INVALID;
                        linfo[lpages - 1].disallow_lpage = 1;
                }
                ugfn = slot->userspace_addr >> PAGE_SHIFT;
                /*
                 * If the gfn and userspace address are not aligned wrt each
                 * other, disable large page support for this slot.
                 */
                if ((slot->base_gfn ^ ugfn) & (KVM_PAGES_PER_HPAGE(level) - 1)) {
                        for (j = 0; j < lpages; ++j)
                                linfo[j].disallow_lpage = 1;
                }
        }

        if (kvm_page_track_create_memslot(kvm, slot, npages))
                goto out_free;

        return 0;

out_free:
        memslot_rmap_free(slot);

        for (i = 0; i < KVM_NR_PAGE_SIZES; ++i) {
                kvfree(slot->arch.page_attr[i]);
                slot->arch.page_attr[i] = NULL;
                if (i == 0)
                        continue;

                kvfree(slot->arch.lpage_info[i - 1]);
                slot->arch.lpage_info[i - 1] = NULL;
        }
        return -ENOMEM;
}
```
The page_attr is set per pages managed by the memslot. The arch.page_attr points
to the page_attr information for the memslot. 
