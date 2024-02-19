>
A page of a given GPA can be assigned to only private GPA xor shared GPA at one
time.  The GPA can't be accessed simultaneously via both private GPA and shared
GPA.  On guest startup, all the GPAs are assigned as private.  Guest converts
the range of GPA to shared (or private) from private (or shared) by MapGPA
hypercall.  MapGPA hypercall takes the start GPA and the size of the region.  If
the given start GPA is shared, VMM converts the region into shared (if it's
already shared, nop).  If the start GPA is private, VMM converts the region into
private.  It implies the guest won't access the unmapped region. private(or
shared) region after converting to shared(or private).
>
If the guest TD triggers an EPT violation on the already converted region, the
access won't be allowed (loop in EPT violation) until other vcpu converts back
the region.



### VMM TDX side handling 
```cpp
static int handle_tdvmcall(struct kvm_vcpu *vcpu)
{
        int r;

        switch (tdvmcall_leaf(vcpu)) {
	......
        case TDG_VP_VMCALL_MAP_GPA:
                r = tdx_map_gpa(vcpu);
                break;
```


```cpp
static int tdx_map_gpa(struct kvm_vcpu *vcpu)
{
        struct kvm_memory_slot *slot;
        struct kvm *kvm = vcpu->kvm;
        gpa_t gpa = tdvmcall_a0_read(vcpu);
        gpa_t size = tdvmcall_a1_read(vcpu);
        gpa_t end = gpa + size;
        int ret;

        tdvmcall_set_return_code(vcpu, TDG_VP_VMCALL_INVALID_OPERAND);
        if (!IS_ALIGNED(gpa, 4096) || !IS_ALIGNED(size, 4096) ||
                end < gpa ||
                end > kvm_gfn_shared_mask(kvm) << (PAGE_SHIFT + 1) ||
                kvm_is_private_gpa(kvm, gpa) != kvm_is_private_gpa(kvm, end))
                return 1;

        tdvmcall_set_return_code(vcpu, TDG_VP_VMCALL_SUCCESS);

        /*
         * TODO: Add memfile notifier on changing private/shared.  Wire the
         *       callback to kvm_mmu_map_gpa().
         */
        ret = kvm_mmu_map_gpa(vcpu, gpa, end);
        if (ret) {
                tdvmcall_set_return_code(vcpu,
                                         TDG_VP_VMCALL_INVALID_OPERAND);
                return 1;
        }

        gpa = gpa & ~gfn_to_gpa(kvm_gfn_shared_mask(vcpu->kvm));
        slot = kvm_vcpu_gfn_to_memslot(vcpu, gpa_to_gfn(gpa));
        if (slot && kvm_slot_is_private(slot))
                return tdx_vp_vmcall_to_user(vcpu);

        return 1;
}
```


## VMM MMU side handling
### Page type of TD-VM accessible pages 
To distinguish page type, mainly whether it is private or shared, TDX adds 
**kvm_arch_memory_slot** type member field arch in the memslot which translates 
GPA to HVA. Note that its sole purpose is tracking TD-VM pages from VMM side. 

```cpp
struct kvm_memory_slot {                          
        struct hlist_node id_node[2];
        struct interval_tree_node hva_node[2];
        struct rb_node gfn_node[2];
        gfn_t base_gfn;
        unsigned long npages;
        unsigned long *dirty_bitmap;
        struct kvm_arch_memory_slot arch;
        unsigned long userspace_addr;
        u32 flags; 
        short id;       
        u16 as_id;
        struct file *private_file;
        loff_t private_offset;
        struct memfile_notifier notifier;
        struct kvm *kvm;
};      
```

```cpp
struct kvm_arch_memory_slot {
        struct kvm_rmap_head *rmap[KVM_NR_PAGE_SIZES];
        struct kvm_page_attr *page_attr[KVM_NR_PAGE_SIZES];
        struct kvm_lpage_info *lpage_info[KVM_NR_PAGE_SIZES - 1];
        unsigned short *gfn_track[KVM_PAGE_TRACK_MAX];
};        

enum kvm_page_type {
        KVM_PAGE_TYPE_INVALID,
        KVM_PAGE_TYPE_SHARED,
        KVM_PAGE_TYPE_PRIVATE,
        KVM_PAGE_TYPE_MIXED,
};                      

struct kvm_page_attr {
        enum kvm_page_type type;
};
```


## Update page type following TD-VM's request
MapGPA -> tdx_map_gpa -> kvm_mmu_map_gpa

The main role of kvm_mmu_map_gpa function are below: 
1. update the page type of given GPA range in memslot->page_attr[];
2. zap existing GPA range when the page type changes;

```cpp
int kvm_mmu_map_gpa(struct kvm_vcpu *vcpu, gpa_t start_gpa, gpa_t end_gpa)
{
        struct kvm_memory_slot *memslot;
        struct kvm_memslot_iter iter;
        struct kvm *kvm = vcpu->kvm;
        struct kvm_memslots *slots;
        gfn_t start, end;
        bool is_private;
        
        if (!kvm_gfn_shared_mask(kvm))
                return -EOPNOTSUPP; 
                
        is_private = kvm_is_private_gpa(kvm, start_gpa);
        start = gpa_to_gfn(start_gpa) & ~kvm_gfn_shared_mask(kvm);
        end = gpa_to_gfn(end_gpa) & ~kvm_gfn_shared_mask(kvm);

        slots = __kvm_memslots(kvm, 0 /* only normal ram. not SMM. */);
        kvm_for_each_memslot_in_gfn_range(&iter, slots, start, end) {
                memslot = iter.slot;
                start = max(start, memslot->base_gfn);
                end = min(end, memslot->base_gfn + memslot->npages);
        
                if (WARN_ON_ONCE(start >= end))
                                continue;
        
                kvm_mmu_map_gfn_in_slot(kvm, memslot, start, end, is_private);
        }       
                
        return 0;
}  
```

It iterates all memslot whose gfn is overlapped the specified range and update
and zap the addresses mapped to the memslot. 


```cpp
static void kvm_mmu_map_gfn_in_slot(struct kvm *kvm,
                                    struct kvm_memory_slot *memslot,
                                    gfn_t start_gfn, gfn_t end_gfn,
                                    bool is_private)
{       
        enum pg_level level;
        
        while (start_gfn < end_gfn) {
                for (level = KVM_MAX_HUGEPAGE_LEVEL; level > PG_LEVEL_4K; level--) {
                        if (start_gfn & (KVM_PAGES_PER_HPAGE(level) - 1))
                                continue;
        
                        if (roundup(start_gfn + 1, KVM_PAGES_PER_HPAGE(level)) > end_gfn)
                                continue;
        
                        break;
                }

                __kvm_mmu_map_gfn_in_slot(kvm, memslot, start_gfn, level, is_private);
                start_gfn += KVM_PAGES_PER_HPAGE(level);

                if (need_resched()) 
                        cond_resched();
        }
}
```

```cpp
static void __kvm_mmu_map_gfn_in_slot(struct kvm *kvm,
                                      struct kvm_memory_slot *memslot,
                                      gfn_t gfn, enum pg_level target_level,
                                      bool is_private)
{
        struct kvm_page_attr *page_attr;
        enum kvm_page_type page_type = is_private ? KVM_PAGE_TYPE_PRIVATE
                                                  : KVM_PAGE_TYPE_SHARED;
        enum pg_level level;

        for (level = KVM_MAX_HUGEPAGE_LEVEL; level > target_level; level--) {
                page_attr = page_attr_on_level(gfn, memslot, level);

                if (!kvm_page_type_valid(page_attr))
                        continue;

                if (page_attr->type == page_type)
                        return;

                split_page_type(gfn, memslot, level);
        }

        /* Zap the gfn at @level when the page type changes */
        if (update_page_type(gfn, memslot, level, page_type)) {
                __zap_gfn_range(kvm, gfn, gfn + KVM_PAGES_PER_HPAGE(level),
                                !is_private);
                try_merge_page_type(gfn, memslot, level);
        }
}
```

### Update page type
>
KVM MMU records which GPA is allowed to access, private or shared.  It steals
software usable bit from MMU present mask.  SPTE_SHARED_MASK.  The bit is
recorded in both shared EPT and the mirror of secure EPT.

```cpp
static bool update_page_type(gfn_t gfn, struct kvm_memory_slot *slot,
                             enum pg_level level, enum kvm_page_type type)
{
        struct kvm_page_attr *page_attr;
        gfn_t base_gfn;
        int i;

        if (level < PG_LEVEL_4K) {
                WARN_ON_ONCE(1);
                return false;
        }

        page_attr = page_attr_on_level(gfn, slot, level);
        if (WARN_ON_ONCE(page_attr->type == KVM_PAGE_TYPE_INVALID))
                return false;

        if (page_attr->type == type)
                return false;

        page_type_set(page_attr, type, gfn, slot, level);

        if (level == PG_LEVEL_4K)
                return true;

        base_gfn = gfn & ~(KVM_PAGES_PER_HPAGE(level) - 1);
        for (i = 0; i < PT64_ENT_PER_PAGE; i++)
                update_page_type(base_gfn + i * KVM_PAGES_PER_HPAGE(level - 1),
                                 slot, level - 1, type);

        return true;
}
```

```cpp
static void page_type_set(
        struct kvm_page_attr *page_attr, enum kvm_page_type type,
        gfn_t gfn, struct kvm_memory_slot *slot, enum pg_level level)
{
        if (page_attr->type == type)
                return;

        /* MIXED => SHARED or PRIVATE */
        if (level > PG_LEVEL_4K && level < KVM_MAX_HUGEPAGE_LEVEL &&
            page_attr->type == KVM_PAGE_TYPE_MIXED &&
            (type == KVM_PAGE_TYPE_SHARED || type == KVM_PAGE_TYPE_PRIVATE))
                __kvm_mmu_gfn_allow_lpage(slot, gfn, level + 1);

        /* PRIVATE or SHARED => MIXED */
        if (level > PG_LEVEL_4K && level < KVM_MAX_HUGEPAGE_LEVEL &&
            (page_attr->type == KVM_PAGE_TYPE_SHARED ||
             page_attr->type == KVM_PAGE_TYPE_PRIVATE) &&
            type == KVM_PAGE_TYPE_MIXED)
            __kvm_mmu_gfn_disallow_lpage(slot, gfn, level + 1);

        page_attr->type = type;
}
```

### Zap opposite type of page
```cpp
/* Invalidate (zap) SPTEs from [gfn_start, gfn_end) of is_private. */
static void __zap_gfn_range(struct kvm *kvm, gfn_t gfn_start, gfn_t gfn_end,
                            bool is_private)
{
        bool flush = false;
        int i;

        /* Legacy MMU isn't supported yet. */
        if (WARN_ON_ONCE(!is_tdp_mmu_enabled(kvm)))
                return;

        if (WARN_ON_ONCE(gfn_end <= gfn_start))
                return;

        write_lock(&kvm->mmu_lock);
        kvm_inc_notifier_count(kvm, gfn_start, gfn_end);

        for (i = 0; i < KVM_ADDRESS_SPACE_NUM; i++)
                flush = __kvm_tdp_mmu_zap_leafs(kvm, i, gfn_start, gfn_end,
                                                true, flush, true, is_private);

        if (flush)
                kvm_flush_remote_tlbs_with_address(kvm, gfn_start,
                                                   gfn_end - gfn_start);

        kvm_dec_notifier_count(kvm, gfn_start, gfn_end);
        write_unlock(&kvm->mmu_lock);
}
```

```cpp
                
bool __kvm_tdp_mmu_zap_leafs(struct kvm *kvm, int as_id, gfn_t start, gfn_t end,
                             bool can_yield, bool flush, bool drop_private,
                             bool is_private)
{                       
        struct kvm_mmu_page *root;
                
        for_each_tdp_mmu_root_yield_safe(kvm, root, as_id) {
                if (is_private != is_private_sp(root))
                        continue;
                flush = tdp_mmu_zap_leafs(kvm, root, start, end, can_yield, flush,
                                          drop_private && is_private_sp(root));
        }                       
                
        return flush;
}

/*
 * Tears down the mappings for the range of gfns, [start, end), and frees the
 * non-root pages mapping GFNs strictly within that range. Returns true if
 * SPTEs have been cleared and a TLB flush is needed before releasing the
 * MMU lock.
 */     
bool kvm_tdp_mmu_zap_leafs(struct kvm *kvm, int as_id, gfn_t start, gfn_t end,
                           bool can_yield, bool flush, bool drop_private)
{               
        struct kvm_mmu_page *root;
                                
        for_each_tdp_mmu_root_yield_safe(kvm, root, as_id)
                flush = tdp_mmu_zap_leafs(kvm, root, start, end, can_yield, flush,
                                          drop_private && is_private_sp(root));

        return flush;
}
```




### Large page setting (lpage)
```cpp

void __kvm_mmu_gfn_disallow_lpage(const struct kvm_memory_slot *slot, gfn_t gfn,
                                  int level)
{
        __update_gfn_disallow_lpage_count(slot, gfn, 1, level);
}

void __kvm_mmu_gfn_allow_lpage(const struct kvm_memory_slot *slot, gfn_t gfn,
                               int level)
{
        __update_gfn_disallow_lpage_count(slot, gfn, -1, level);
}

static void __update_gfn_disallow_lpage_count(const struct kvm_memory_slot *slot,
                                            gfn_t gfn, int count, int level)
{
        struct kvm_lpage_info *linfo;

        if (WARN_ON(level <= PG_LEVEL_4K))
                return;

        linfo = lpage_info_slot(gfn, slot, level);
        linfo->disallow_lpage += count;
        WARN_ON(linfo->disallow_lpage < 0);
}

static struct kvm_lpage_info *lpage_info_slot(gfn_t gfn,
                const struct kvm_memory_slot *slot, int level)
{
        unsigned long idx;

        idx = gfn_to_index(gfn, slot->base_gfn, level);
        return &slot->arch.lpage_info[level - PG_LEVEL_2M][idx];
}
```


```cpp
1039 /*
1040  * Inform the VMM of the guest's intent for this physical page: shared with
1041  * the VMM or private to the guest.  The VMM is expected to change its mapping
1042  * of the page in response.
1043  */
1044 static bool tdx_enc_status_changed(unsigned long vaddr, int numpages, bool enc)
1045 {
1046         phys_addr_t start = __pa(vaddr);
1047         phys_addr_t end = __pa(vaddr + numpages * PAGE_SIZE);
1048 
1049         return tdx_enc_status_changed_phys(start, end, enc);
1050 }
```

