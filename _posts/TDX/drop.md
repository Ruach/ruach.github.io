## Register handler for private memory
>TDX patch introduces memfile_notifier facility so existing memory file
subsystems (e.g. tmpfs/hugetlbfs) can provide memory pages to allow a
third kernel component to make use of memory bookmarked in the memory
file and gets notified when the pages in the memory file become
allocated/invalidated.
>
>It will be used for KVM to use a file descriptor as the guest memory
backing store and KVM will use this memfile_notifier interface to
interact with memory file subsystems. In the future there might be other
consumers (e.g. VFIO with encrypted device memory).
>
>It consists below components:
> - memfile_backing_store: Each supported memory file subsystem can be
   implemented as a memory backing store which bookmarks memory and
   provides callbacks for other kernel systems (memfile_notifier
   consumers) to interact with.
> - memfile_notifier: memfile_notifier consumers defines callbacks and
   associate them to a file using memfile_register_notifier().
> - memfile_node: A memfile_node is associated with the file (inode) from
   the backing store and includes feature flags and a list of registered
   memfile_notifier for notifying.
>
>Userspace is in charge of guest memory lifecycle: it first allocates
pages in memory backing store and then passes the fd to KVM and lets KVM
register memory slot to memory backing store via
memfile_register_notifier.

### Data structure related with registration 
```cpp
struct memfile_node {
        struct list_head        notifiers;      /* registered memfile_notifier list on the file */
        unsigned long           flags;          /* MEMFILE_F_* flags */
};

struct memfile_backing_store {
        struct list_head list;
        spinlock_t lock;
        struct memfile_node* (*lookup_memfile_node)(struct file *file);
        int (*get_lock_pfn)(struct file *file, pgoff_t offset, pfn_t *pfn,
                            int *order);
        void (*put_unlock_pfn)(pfn_t pfn);
};      
        
struct memfile_notifier;
struct memfile_notifier_ops {
        void (*populate)(struct memfile_notifier *notifier,
                         pgoff_t start, pgoff_t end);
        void (*invalidate)(struct memfile_notifier *notifier,
                           pgoff_t start, pgoff_t end);
};      
        
struct memfile_notifier {
        struct list_head list;
        struct memfile_notifier_ops *ops;
        struct memfile_backing_store *bs;
};
```

### Operations for registering backing store handler
```cpp
static inline int kvm_private_mem_register(struct kvm_memory_slot *slot)
{
        slot->notifier.ops = &kvm_private_mem_notifier_ops;
        return memfile_register_notifier(slot->private_file, KVM_MEMFILE_FLAGS,
                                         &slot->notifier);
}       
```

```cpp
int memfile_register_notifier(struct file *file, unsigned long flags,
                              struct memfile_notifier *notifier)
{
        struct memfile_backing_store *bs;
        struct memfile_node *node;
        struct list_head *list;

        if (!file || !notifier || !notifier->ops)
                return -EINVAL;
        if (flags & ~MEMFILE_F_ALLOWED_MASK)
                return -EINVAL;

        list_for_each_entry(bs, &backing_store_list, list) {
                node = bs->lookup_memfile_node(file);
                if (node) {
                        list = &node->notifiers;
                        notifier->bs = bs;

                        spin_lock(&bs->lock);
                        if (list_empty(list))
                                node->flags = flags;
                        else if (node->flags ^ flags) {
                                spin_unlock(&bs->lock);
                                return -EINVAL;
                        }

                        list_add_rcu(&notifier->list, list);
                        spin_unlock(&bs->lock);
                        memfile_node_update_flags(file, flags);
                        return 0;
                }
        }

        return -EOPNOTSUPP;
}
```

### Shmem as a memfile_notifier backing store
```cpp
struct shmem_inode_info {
        spinlock_t              lock;
        unsigned int            seals;          /* shmem seals */
        unsigned long           flags;
        unsigned long           alloced;        /* data pages alloced to file */
        unsigned long           swapped;        /* subtotal assigned to swap */
        pgoff_t                 fallocend;      /* highest fallocate endindex */
        struct list_head        shrinklist;     /* shrinkable hpage inodes */
        struct list_head        swaplist;       /* chain of maybes on swap */
        struct shared_policy    policy;         /* NUMA memory alloc policy */
        struct simple_xattrs    xattrs;         /* list of xattrs */
        atomic_t                stop_eviction;  /* hold when working on inode */
        struct timespec64       i_crtime;       /* file creation time */
        struct memfile_node     memfile_node;   /* memfile node */
        struct inode            vfs_inode;
};              
```

```cpp
static void notify_populate(struct inode *inode, pgoff_t start, pgoff_t end)
{
        struct shmem_inode_info *info = SHMEM_I(inode);

        memfile_notifier_populate(&info->memfile_node, start, end);
}

static void notify_invalidate(struct inode *inode, struct folio *folio,
                                   pgoff_t start, pgoff_t end)
{
        struct shmem_inode_info *info = SHMEM_I(inode);

        start = max(start, folio->index);
        end = min(end, folio->index + folio_nr_pages(folio));

        memfile_notifier_invalidate(&info->memfile_node, start, end);
}

```

### What operations are done for private backing store? 
```cpp
static struct memfile_notifier_ops kvm_private_mem_notifier_ops = {
        .populate = kvm_private_mem_notifier_handler,
        .invalidate = kvm_private_mem_notifier_handler,
};    
```

```cpp
#ifdef CONFIG_HAVE_KVM_PRIVATE_MEM
static void kvm_private_mem_notifier_handler(struct memfile_notifier *notifier,
                                             pgoff_t start, pgoff_t end)
{
        int idx;
        struct kvm_memory_slot *slot = container_of(notifier,
                                                    struct kvm_memory_slot,
                                                    notifier);
        struct kvm_gfn_range gfn_range = {
                .slot           = slot,
                .start          = start - (slot->private_offset >> PAGE_SHIFT),
                .end            = end - (slot->private_offset >> PAGE_SHIFT),
                .may_block      = true,
        };
        struct kvm *kvm = slot->kvm;

        if (start < (slot->private_offset >> PAGE_SHIFT) ||
            end < (slot->private_offset >> PAGE_SHIFT))
                return;

        gfn_range.start = slot->base_gfn + gfn_range.start;
        gfn_range.end = slot->base_gfn + min((unsigned long)gfn_range.end, slot->npages);

        if (WARN_ON_ONCE(gfn_range.start >= gfn_range.end))
                return;

        idx = srcu_read_lock(&kvm->srcu);
        KVM_MMU_LOCK(kvm);
        if (kvm_unmap_gfn_range(kvm, &gfn_range))
                kvm_flush_remote_tlbs(kvm);
        kvm->mmu_notifier_seq++;
        KVM_MMU_UNLOCK(kvm);
        srcu_read_unlock(&kvm->srcu, idx);
}
```





# Drop spte 
```cpp
static void drop_spte(struct kvm *kvm, u64 *sptep)
{
        u64 old_spte = mmu_spte_clear_track_bits(kvm, sptep);

        if (is_shadow_present_pte(old_spte) ||
            is_private_zapped_spte(old_spte))
                rmap_remove(kvm, sptep, old_spte);
}
```

The spte should be zapped to be dropped, so the zapping should have been invoked
before calling the drop_spte function.

## Zapping spte
```cpp
int kvm_tdp_mmu_map(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault)
                ......
                /*
                 * If there is an SPTE mapping a large page at a higher level
                 * than the target, that SPTE must be cleared and replaced
                 * with a non-leaf SPTE.
                 */
                if (is_shadow_present_pte(iter.old_spte) &&
                    is_large_pte(iter.old_spte)) {
                        if (is_private) {
                                tdp_mmu_split_pivate_huge_page(vcpu, &iter,
                                                               fault, true);
                                break;
                        } else {
                                if (tdp_mmu_zap_spte_atomic(vcpu->kvm, &iter))
                                        break;
                        }
                        WARN_ON(is_private_sptep(iter.sptep));

                        /*
                         * The iter must explicitly re-read the spte here
                         * because the new value informs the !present
                         * path below.
                         */
                        iter.old_spte = kvm_tdp_mmu_read_spte(iter.sptep);
                }

```


```cpp
static inline int tdp_mmu_zap_spte_atomic(struct kvm *kvm,
                                          struct tdp_iter *iter)
{
        int ret;

        /*
         * Freeze the SPTE by setting it to a special,
         * non-present value. This will stop other threads from
         * immediately installing a present entry in its place
         * before the TLBs are flushed.
         */
        ret = tdp_mmu_set_spte_atomic(kvm, iter, REMOVED_SPTE);
        if (ret)
                return ret;

        kvm_flush_remote_tlbs_with_address(kvm, iter->gfn,
                                           KVM_PAGES_PER_HPAGE(iter->level));

        /*
         * No other thread can overwrite the removed SPTE as they must either
         * wait on the MMU lock or use tdp_mmu_set_spte_atomic() which will not
         * overwrite the special removed SPTE value. No bookkeeping is needed
         * here since the SPTE is going from non-present to non-present.  Use
         * the raw write helper to avoid an unnecessary check on volatile bits.
         *
         * Set non-present value to SHADOW_NONPRESENT_VALUE, rather than 0.
         * It is because when TDX is enabled, TDX module always
         * enables "EPT-violation #VE", so KVM needs to set
         * "suppress #VE" bit in EPT table entries, in order to get
         * real EPT violation, rather than TDVMCALL.  KVM sets
         * SHADOW_NONPRESENT_VALUE (which sets "suppress #VE" bit) so it
         * can be set when EPT table entries are zapped.
         */
        __kvm_tdp_mmu_write_spte(iter->sptep, private_zapped_spte(kvm, iter));

        return 0;
}


```






### Checking whether the page has been zapped
```cpp
/*
 * A MMU present SPTE is backed by actual memory and may or may not be present
 * in hardware.  E.g. MMIO SPTEs are not considered present.  Use bit 11, as it
 * is ignored by all flavors of SPTEs and checking a low bit often generates
 * better code than for a high bit, e.g. 56+.  MMU present checks are pervasive
 * enough that the improved code generation is noticeable in KVM's footprint.
 */
#define SPTE_MMU_PRESENT_MASK           BIT_ULL(11)

/* Masks that used to track metadata for not-present SPTEs. */
#define SPTE_PRIVATE_ZAPPED     BIT_ULL(62)
```

```cpp
static inline bool is_shadow_present_pte(u64 pte)
{
        return !!(pte & SPTE_MMU_PRESENT_MASK);
}
```

```cpp
static inline bool is_private_zapped_spte(u64 spte)
{       
        return !!(spte & SPTE_PRIVATE_ZAPPED);
}       
```

### Zapping!
```cpp
static u64 private_zapped_spte(struct kvm *kvm, const struct tdp_iter *iter)
{
        if (!kvm_gfn_shared_mask(kvm))
                return SHADOW_NONPRESENT_VALUE;

        if (!iter->is_private)
                return SHADOW_NONPRESENT_VALUE;

        return SHADOW_NONPRESENT_VALUE | SPTE_PRIVATE_ZAPPED |
                (spte_to_pfn(iter->old_spte) << PAGE_SHIFT) |
                (is_large_pte(iter->old_spte) ? PT_PAGE_SIZE_MASK : 0);
}
```

```cpp
static bool kvm_mmu_zap_private_spte(struct kvm *kvm, u64 *sptep)
{
        u64 clear_bits;
        kvm_pfn_t pfn;
        bool ret;

        ret = __kvm_mmu_zap_private_spte(kvm, sptep);
        if (!ret)
                return ret;

        pfn = spte_to_pfn(*sptep);
        clear_bits = SPTE_PRIVATE_ZAPPED | (pfn << PAGE_SHIFT) |
                (is_large_pte(*sptep) ? PT_PAGE_SIZE_MASK : 0);
        __mmu_spte_clear_track_bits(kvm, sptep, clear_bits);
        return ret;
}
```

### Zap through rmmap
```cpp
static bool kvm_zap_rmapp(struct kvm *kvm, struct kvm_rmap_head *rmap_head,
                        const struct kvm_memory_slot *slot)
{                     
        return __kvm_zap_rmapp(kvm, rmap_head);
}                     
                
static bool kvm_unmap_rmapp(struct kvm *kvm, struct kvm_rmap_head *rmap_head,
                            struct kvm_memory_slot *slot, gfn_t gfn, int level,
                            pte_t unused)
{       
        return __kvm_zap_rmapp(kvm, rmap_head);
}             
```

Usually the kvm_zap_rmap is invoked when system register is changed, so unmap
function is more likely to be invoked. Why unmap interface is needed ? 


```cpp
bool kvm_unmap_gfn_range(struct kvm *kvm, struct kvm_gfn_range *range)
{       
        bool flush = false;

        if (kvm_memslots_have_rmaps(kvm))
                flush = kvm_handle_gfn_range(kvm, range, kvm_unmap_rmapp);
                            
        if (is_tdp_mmu_enabled(kvm))
                /*              
                 * private page needs to be kept and handle page migration
                 * on next EPT violation.
                 */
                flush = kvm_tdp_mmu_unmap_gfn_range(kvm, range, flush, false);
        
        return flush;
}    
```





```cpp
static void rmap_add(struct kvm_vcpu *vcpu, struct kvm_memory_slot *slot,
                     u64 *spte, gfn_t gfn)
{               
        struct kvm_mmu_page *sp;
        struct kvm_rmap_head *rmap_head;
        int rmap_count;

        sp = sptep_to_sp(spte);
        kvm_mmu_page_set_gfn(sp, spte - sp->spt, gfn);
        rmap_head = gfn_to_rmap(gfn, sp->role.level, slot);
        rmap_count = pte_list_add(vcpu, spte, rmap_head);

        if (rmap_count > RMAP_RECYCLE_THRESHOLD) {
                kvm_unmap_rmapp(vcpu->kvm, rmap_head, NULL, gfn, sp->role.level, __pte(0));
                kvm_flush_remote_tlbs_with_address(
                                vcpu->kvm, sp->gfn, KVM_PAGES_PER_HPAGE(sp->role.level));
        }       
}
```

```cpp
static bool __kvm_zap_rmapp(struct kvm *kvm, struct kvm_rmap_head *rmap_head)
{
        struct pte_list_desc *desc, *prev, *next;
        bool flush = false;
        u64 *sptep;
        int i;

        if (!rmap_head->val)
                return false;

        if (!(rmap_head->val & 1)) {
retry_head:
                sptep = (u64 *)rmap_head->val;
                if (is_private_zapped_spte(*sptep))
                        return flush;

                flush = true;
                /* Keep the rmap if the private SPTE couldn't be zapped. */
                if (kvm_mmu_zap_private_spte(kvm, sptep))
                        goto retry_head;

                mmu_spte_clear_track_bits(kvm, (u64 *)rmap_head->val);
                rmap_head->val = 0;
                return true;
        }

retry:
        prev = NULL;
        desc = (struct pte_list_desc *)(rmap_head->val & ~1ul);

        for (; desc; desc = next) {
                for (i = 0; i < desc->spte_count; i++) {
                        sptep = desc->sptes[i];
                        if (is_private_zapped_spte(*sptep))
                                continue;

                        flush = true;
                        /*
                         * Keep the rmap if the private SPTE couldn't be
                         * zapped.
                         */
                        if (kvm_mmu_zap_private_spte(kvm, sptep))
                                goto retry;

                        mmu_spte_clear_track_bits(kvm, desc->sptes[i]);

                        desc->spte_count--;
                        desc->sptes[i] = desc->sptes[desc->spte_count];
                        desc->sptes[desc->spte_count] = NULL;
                        i--;    /* start from same index. */
                }

                next = desc->more;
                if (desc->spte_count) {
                        prev = desc;
                } else {
                        if (!prev && !desc->more)
                                rmap_head->val = 0;
                        else
                                if (prev)
                                        prev->more = next;
                                else
                                        rmap_head->val = (unsigned long)desc->more | 1;
                        mmu_free_pte_list_desc(desc);
                }
        }

        return flush;
}
```



Main function to drop the spte page (when it is secure or shared)
```cpp
static void rmap_remove(struct kvm *kvm, u64 *spte, u64 old_spte)
{                       
        struct kvm_memslots *slots;
        struct kvm_memory_slot *slot;
        struct kvm_mmu_page *sp;
        gfn_t gfn;
        struct kvm_rmap_head *rmap_head;
                        
        sp = sptep_to_sp(spte);
        gfn = kvm_mmu_page_get_gfn(sp, spte - sp->spt);
                        
        /*              
         * Unlike rmap_add, rmap_remove does not run in the context of a vCPU
         * so we have to determine which memslots to use based on context
         * information in sp->role.
         */                     
        slots = kvm_memslots_for_spte_role(kvm, sp->role);
                
        slot = __gfn_to_memslot(slots, gfn);
        rmap_head = gfn_to_rmap(gfn, sp->role.level, slot);
        
        __pte_list_remove(spte, rmap_head);
                        
        if (is_private_sp(sp))
                static_call(kvm_x86_drop_private_spte)(
                        kvm, gfn, sp->role.level, spte_to_pfn(old_spte));
}
```





### Some places where the drop_spte is invoked 

```cpp
static bool kvm_drop_private_zapped_rmapp(
        struct kvm *kvm, struct kvm_rmap_head *rmap_head,
        const struct kvm_memory_slot *slot)
{
        u64 *sptep;
        struct rmap_iterator iter;

        for_each_rmap_spte(rmap_head, &iter, sptep) {
                if (!is_private_zapped_spte(*sptep))
                        continue;

                drop_spte(kvm, sptep);
        }

        return false;
}
```


called by kvm_mmu_page_unlink_children or kvm_mmu_pte_write
```cpp
/* Returns the number of zapped non-leaf child shadow pages. */
static int mmu_page_zap_pte(struct kvm *kvm, struct kvm_mmu_page *sp,
                            u64 *spte, struct list_head *invalid_list)
{
        u64 pte;
        struct kvm_mmu_page *child;

        pte = *spte;
        if (is_shadow_present_pte(pte) || is_private_zapped_spte(pte)) {
                if (is_last_spte(pte, sp->role.level)) {
                        drop_spte(kvm, spte);
                } else {
                        child = to_shadow_page(pte & PT64_BASE_ADDR_MASK);
                        drop_parent_pte(child, spte);

                        if (!is_shadow_present_pte(pte))
                                return 0;

                        /*
                         * Recursively zap nested TDP SPs, parentless SPs are
                         * unlikely to be used again in the near future.  This
                         * avoids retaining a large number of stale nested SPs.
                         */
                        if (tdp_enabled && invalid_list &&
                            child->role.guest_mode && !child->parent_ptes.val)
                                return kvm_mmu_prepare_zap_page(kvm, child,
                                                                invalid_list);
                }
        } else if (!is_private_sp(sp) && is_mmio_spte(kvm, pte)) {
                mmu_spte_clear_no_track(spte);
        }
        return 0;
        }

```



## Zaapping rmapp
```cpp
void kvm_zap_gfn_range(struct kvm *kvm, gfn_t gfn_start, gfn_t gfn_end)
{
        bool flush;
        int i;

        if (WARN_ON_ONCE(gfn_end <= gfn_start))
                return;

        write_lock(&kvm->mmu_lock);

        kvm_inc_notifier_count(kvm, gfn_start, gfn_end);

        flush = __kvm_zap_rmaps(kvm, gfn_start, gfn_end);

        if (is_tdp_mmu_enabled(kvm)) {
                for (i = 0; i < KVM_ADDRESS_SPACE_NUM; i++)
                        flush = kvm_tdp_mmu_zap_leafs(kvm, i, gfn_start,
                                                      gfn_end, true, flush, false);
        }

        if (flush)
                kvm_flush_remote_tlbs_with_address(kvm, gfn_start,
                                                   gfn_end - gfn_start);

        kvm_dec_notifier_count(kvm, gfn_start, gfn_end);

        write_unlock(&kvm->mmu_lock);
}
```


This functions is only invoked when some specific registers are invoked, I don't
know what is the difference between this function and 


```cpp
static void kvm_mmu_invalidate_zap_pages_in_memslot(struct kvm *kvm,
                        struct kvm_memory_slot *slot,
                        struct kvm_page_track_notifier_node *node)
{
        if (kvm_gfn_shared_mask(kvm))
                kvm_mmu_zap_memslot(kvm, slot);
        else
                kvm_mmu_zap_all_fast(kvm);
}
```

```cpp
static void kvm_mmu_zap_memslot(struct kvm *kvm, struct kvm_memory_slot *slot)
{
        bool flush = false;

        write_lock(&kvm->mmu_lock);

        /*
         * Zapping non-leaf SPTEs, a.k.a. not-last SPTEs, isn't required, worst
         * case scenario we'll have unused shadow pages lying around until they
         * are recycled due to age or when the VM is destroyed.
         */     
        if (is_tdp_mmu_enabled(kvm)) {
                struct kvm_gfn_range range = {
                      .slot = slot,
                      .start = slot->base_gfn,
                      .end = slot->base_gfn + slot->npages,
                      .may_block = false,
                };

                /* All private page should be zapped on memslot deletion. */
                flush = kvm_tdp_mmu_unmap_gfn_range(kvm, &range, flush, true);
        } else {        
```







```cpp
static __always_inline bool kvm_handle_gfn_range(struct kvm *kvm,
                                                 struct kvm_gfn_range *range,
                                                 rmap_handler_t handler)
{
        struct slot_rmap_walk_iterator iterator;
        bool ret = false;

        for_each_slot_rmap_range(range->slot, PG_LEVEL_4K, KVM_MAX_HUGEPAGE_LEVEL,
                                 range->start, range->end - 1, &iterator)
                ret |= handler(kvm, iterator.rmap, range->slot, iterator.gfn,
                               iterator.level, range->pte);
                        
        return ret;   
}  
```











###
```cpp
static bool __kvm_mmu_prepare_zap_page(struct kvm *kvm,
                                       struct kvm_mmu_page *sp,
                                       struct list_head *invalid_list,
                                       int *nr_zapped)
{       
        bool list_unstable, zapped_root = false;
        
        trace_kvm_mmu_prepare_zap_page(sp);
        ++kvm->stat.mmu_shadow_zapped;
        *nr_zapped = mmu_zap_unsync_children(kvm, sp, invalid_list);
        *nr_zapped += kvm_mmu_page_unlink_children(kvm, sp, invalid_list);
        kvm_mmu_unlink_parents(sp);     
                                        
        /* Zapping children means active_mmu_pages has become unstable. */
        list_unstable = *nr_zapped;
        
        if (!sp->role.invalid && sp_has_gptes(sp))
                unaccount_shadowed(kvm, sp);
                
        if (sp->unsync)
                kvm_unlink_unsync_page(kvm, sp);
        if (!sp->root_count) {


```




