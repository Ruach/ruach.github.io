# Data structure-wise changes for TDX
## Repurposing SPT for S-EPT
>The difference is, that S-EPT is operated(read/write) **via TDX SEAM call** 
>which is expensive instead of direct read/write EPT entry. 

The difference between vanilla VM and TD VM in page fault handling is mainly 
comes from the location of the SPT is within the TDX module, which is not 
accessible from the host VMM. 



### Motivation of the repurposing 
>The difference is, that S-EPT is operated(read/write) via TDX SEAM call which 
>is expensive instead of direct read/write EPT entry. For performance, minimize
>TDX SEAM call to operate on S-EPT. When getting corresponding S-EPT pages/entry
>from faulting GPA, don't use TDX SEAM call to read S-EPT entry. Instead create 
>**shadow copy in host memory**. Repurpose the existing **kvm_mmu_page** as 
>shadow copy of S-EPT and associate S-EPT to it.

The page table used for accessing private pages inside TD VM (S-EPT), can be 
configured by the VMM through the SEAM call because memories allotted to TD VM 
is not accessible from the VMM side. However, it is very expensive interface,
so KVM mirros TDX's S-EPT using shadow pages (SPT). This costs extra memory to 
build S-EPT in TDX module and host KVM side, but simpler and efficient because
it does not invoke SEAMCALL to read the SEPT during page table walks to resolve
page fault occurred inside TD VM.


### Struct kvm_mmu_page
The principal data structure is again **kvm_mmu_page** because host VMM side 
mirrors S-EPT using spte. Intel TDX adds one more field called **private_sp** 
for XXX.

```cpp
 33 struct kvm_mmu_page {
......
 46         /*
 47          * The following two entries are used to key the shadow page in the
 48          * hash table.
 49          */
 50         union kvm_mmu_page_role role;
 51         gfn_t gfn;
 52         gfn_t gfn_stolen_bits;
 53
 54         u64 *spt;
 55         /* hold the gfn of each spte inside spt */
 56         gfn_t *gfns;
 57         /* associated private shadow page, e.g. SEPT page */
 58         void *private_sp;
```

```cpp
static inline void kvm_mmu_alloc_private_sp(
        struct kvm_vcpu *vcpu, struct kvm_mmu_page *sp, bool is_root)
{
        if (is_root)
                sp->private_sp = KVM_MMU_PRIVATE_SP_ROOT;
        else
                sp->private_sp = kvm_mmu_memory_cache_alloc(
                        &vcpu->arch.mmu_private_sp_cache);
        /*
         * Because mmu_private_sp_cache is topped up before staring kvm page
         * fault resolving, the allocation above shouldn't fail.
         */
        WARN_ON_ONCE(!sp->private_sp);
}

```


### SPTE_PRIVATE_ZAPPED bit of spte
TDX needs one more mask bit regarding spte, SPTE_PRIVATE_ZAPPED. Steal 1 bit
from MMIO generation as 62 bit and re-purpose it to track non-present SPTE.

**arch/x86/kvm/mmu/spte.h**
```cpp
 18 #define SPTE_PRIVATE_ZAPPED     BIT_ULL(62)
```

## Shared and Private GPA
KVM MMU needs to be enhanced to handle Secure/Shared-EPT. 

### Distinguishing shared and private through GPA
>One bit of GPA (51 or 47 bit) is repurposed so that it means shared with host
>(if set to 1) or private to TD(if cleared to 0). Treats share bit as attributes
>mask/unmask the bit where necessary to keep the existing traversing code works.

TDX introduces prviate_mmu_pages list to maintain all private pages and
**gfn_shared_mask** used to distinguish shared memory from private. 

```cpp
1081 struct kvm_arch {
1082         unsigned long vm_type;
1083         unsigned long n_used_mmu_pages;
1084         unsigned long n_requested_mmu_pages;
1085         unsigned long n_max_mmu_pages;
1086         unsigned int indirect_shadow_pages;
1087         int tdp_max_page_level;
1088         u8 mmu_valid_gen;
1089         struct hlist_head mmu_page_hash[KVM_NUM_MMU_PAGES];
1090         struct list_head active_mmu_pages;
1091         struct list_head private_mmu_pages;
......
1278         gfn_t gfn_shared_mask;
1279 };
```

One bit of GPA, 51 or 47 bit based on the width of TD VM's address space, is 
used to distinguish private memories of TD from shared memories. This bit is 
called shared bit, so the page is shared if this bit is set on GPA, but private
if the bit is cleared to 0.

```cpp
2262 static int tdx_td_init(struct kvm *kvm, struct kvm_tdx_cmd *cmd)
2263 {
2320         if (td_params->exec_controls & TDX_EXEC_CONTROL_MAX_GPAW)
2321                 kvm->arch.gfn_shared_mask = BIT_ULL(51) >> PAGE_SHIFT;
2322         else
2323                 kvm->arch.gfn_shared_mask = BIT_ULL(47) >> PAGE_SHIFT;
```
Based on the GPAW field, the location of the shared mask bit is changed (51 or
47). The information of the shared bit is stored in gfn_shared_mask field of 
kvm arch struct. 

### Interface functions related with shared bit masking
```cpp
1123 static inline bool is_private_gfn(struct kvm_vcpu *vcpu, gfn_t gfn_stolen_bits)
1124 {
1125         return __is_private_gfn(vcpu->kvm, gfn_stolen_bits);
1126 }

1128 static inline bool is_private_spte(struct kvm *kvm, u64 *sptep)
1129 {
1130         return __is_private_gfn(kvm, sptep_to_sp(sptep)->gfn_stolen_bits);
1131 }

1116 static inline bool __is_private_gfn(struct kvm *kvm, gfn_t gfn_stolen_bits)
1117 {
1118         gfn_t gfn_shared_mask = kvm->arch.gfn_shared_mask;
1119 
1120         return gfn_shared_mask && !(gfn_shared_mask & gfn_stolen_bits);
1121 }
```

```cpp
283 static inline gfn_t vcpu_gfn_stolen_mask(struct kvm_vcpu *vcpu)
284 {   
285         return kvm_gfn_stolen_mask(vcpu->kvm);
286 }   

278 static inline gfn_t kvm_gfn_stolen_mask(struct kvm *kvm)
279 {
280         return kvm->arch.gfn_shared_mask;
281 }
```

# Logic-wise changes for TDX
## Add Private Memory Pages to TD VM
## Add S-PTE 
### kvm_x86_ops for spte
TDX add kvm_x86_ops hooks to set/clear private SPTEs, i.e. SEPT entries, and to 
link/free private shadow pages, i.e. non-leaf SEPT pages.

```cpp
3289 static int __init tdx_hardware_setup(struct kvm_x86_ops *x86_ops)
3290 {
......
3302         x86_ops->cache_gprs = tdx_cache_gprs;
3303         x86_ops->flush_gprs = tdx_flush_gprs;
3304 
3305         x86_ops->tlb_remote_flush = tdx_sept_tlb_remote_flush;
3306         x86_ops->set_private_spte = tdx_sept_set_private_spte;
3307         x86_ops->drop_private_spte = tdx_sept_drop_private_spte;
3308         x86_ops->zap_private_spte = tdx_sept_zap_private_spte;
3309         x86_ops->unzap_private_spte = tdx_sept_unzap_private_spte;
3310         x86_ops->link_private_sp = tdx_sept_link_private_sp;
3311         x86_ops->free_private_sp = tdx_sept_free_private_sp;
3312         x86_ops->split_private_spte = tdx_sept_split_private_spte;
3313         x86_ops->mem_enc_read_memory = tdx_read_guest_memory;
3314         x86_ops->mem_enc_write_memory = tdx_write_guest_memory;
```

set/unset and zap/unzap private spte functions are important in managing TD
VM memories. 


### Set/Drop private spte
```cpp
static void tdx_sept_set_private_spte(struct kvm_vcpu *vcpu, gfn_t gfn,
                                      enum pg_level level, kvm_pfn_t pfn)
{
        int tdx_level = pg_level_to_tdx_sept_level(level);
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(vcpu->kvm);
        hpa_t hpa = pfn << PAGE_SHIFT;
        gpa_t gpa = gfn << PAGE_SHIFT;
        struct tdx_ex_ret ex_ret;
        hpa_t source_pa;
        u64 err;
        int i;

        if (WARN_ON_ONCE(is_error_noslot_pfn(pfn) || kvm_is_reserved_pfn(pfn)))
                return;

        /* Only support 4KB and 2MB pages */
        if (KVM_BUG_ON(level > PG_LEVEL_2M, vcpu->kvm))
                return;

        /* Pin the page, KVM doesn't yet support page migration. */
        for (i = 0; i < KVM_PAGES_PER_HPAGE(level); i++)
                get_page(pfn_to_page(pfn + i));

        /* Build-time faults are induced and handled via TDH_MEM_PAGE_ADD. */
        if (is_td_finalized(kvm_tdx)) {
                trace_kvm_sept_seamcall(SEAMCALL_TDH_MEM_PAGE_AUG, gpa, hpa, tdx_level);

                err = tdh_mem_page_aug(kvm_tdx->tdr.pa, gpa, tdx_level, hpa, &ex_ret);
                SEPT_ERR(err, &ex_ret, TDH_MEM_PAGE_AUG, vcpu->kvm);
                return;
        }

        trace_kvm_sept_seamcall(SEAMCALL_TDH_MEM_PAGE_ADD, gpa, hpa, tdx_level);

        WARN_ON(kvm_tdx->source_pa == INVALID_PAGE);
        source_pa = kvm_tdx->source_pa & ~KVM_TDX_MEASURE_MEMORY_REGION;

        WARN_ON(hpa == source_pa);
        err = tdh_mem_page_add(kvm_tdx->tdr.pa, gpa, tdx_level, hpa, source_pa, &ex_ret);
        if (!SEPT_ERR(err, &ex_ret, TDH_MEM_PAGE_ADD, vcpu->kvm) &&
            (kvm_tdx->source_pa & KVM_TDX_MEASURE_MEMORY_REGION))
                tdx_measure_page(kvm_tdx, gpa, KVM_HPAGE_SIZE(level));

        kvm_tdx->source_pa = INVALID_PAGE;
}
```

First, pin pages via get_page() right before ADD/AUG'ed to TDs. Based on whether
the TD VM has been finalized or not, it invokes different SEAM call AUG or ADD 
to add page to target TD VM distinguished by the TDR. 

```cpp
static void tdx_sept_drop_private_spte(struct kvm *kvm, gfn_t gfn, enum pg_level level,
                                       kvm_pfn_t pfn)
{
        int tdx_level = pg_level_to_tdx_sept_level(level);
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
        gpa_t gpa = gfn << PAGE_SHIFT;
        hpa_t hpa = pfn << PAGE_SHIFT;
        hpa_t hpa_with_hkid;
        struct tdx_ex_ret ex_ret;
        u64 err;
        int i;

        /* Only support 4KB and 2MB pages */
        if (KVM_BUG_ON(level > PG_LEVEL_2M, kvm))
                return;

        if (is_hkid_assigned(kvm_tdx)) {
                trace_kvm_sept_seamcall(SEAMCALL_TDH_MEM_PAGE_REMOVE, gpa, hpa, tdx_level);

                err = tdh_mem_page_remove(kvm_tdx->tdr.pa, gpa, tdx_level, &ex_ret);
                if (SEPT_ERR(err, &ex_ret, TDH_MEM_PAGE_REMOVE, kvm))
                        return;

                for (i = 0; i < KVM_PAGES_PER_HPAGE(level); i++) {
                        hpa_with_hkid = set_hkid_to_hpa(hpa, (u16)kvm_tdx->hkid);
                        err = tdh_phymem_page_wbinvd(hpa_with_hkid);
                        if (TDX_ERR(err, TDH_PHYMEM_PAGE_WBINVD, NULL))
                                return;
                        hpa += PAGE_SIZE;
                }
        } else if (tdx_reclaim_page((unsigned long)__va(hpa), hpa, level)) {
                return;
        }

        for (i = 0; i < KVM_PAGES_PER_HPAGE(level); i++)
                put_page(pfn_to_page(pfn + i));
}
```

Based on the target TD VM's state, here whether the HKID is still bound to the 
target VM instance, it invokes different Seam call. Note that when there is no
associated HKID for TD VM, it means that the VM has been destroyed. The two Seam
call are TDH.MEM.PAGE.REMOVE and TDH_PHYMEM_PAGE_RECLAIM_LEAF. Removing the page
can be done at anytime after the TD VM is completely initialized but before its 
destruction. However, the reclaiming the page is only done when the VM is already
destructed. 


### Zap/Unzap private spte   
For TDX, zap and unzap indicate blocking and unblocking a specific memory page
assigned to TD VM. This operations are associated with SEAMCALL_TDH_MEM_RANGE_BLOCK
and SEAMCALL_TDH_MEM_RANGE_UNBLOCK seamcall. 

```cpp
static void tdx_sept_zap_private_spte(struct kvm *kvm, gfn_t gfn, enum pg_level level)
{
        int tdx_level = pg_level_to_tdx_sept_level(level);
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
        gpa_t gpa = gfn << PAGE_SHIFT;
        struct tdx_ex_ret ex_ret;
        u64 err;

        trace_kvm_sept_seamcall(SEAMCALL_TDH_MEM_RANGE_BLOCK, gpa, -1ull, tdx_level);

        err = tdh_mem_range_block(kvm_tdx->tdr.pa, gpa, tdx_level, &ex_ret);
        SEPT_ERR(err, &ex_ret, TDH_MEM_RANGE_BLOCK, kvm);
}

static void tdx_sept_unzap_private_spte(struct kvm *kvm, gfn_t gfn, enum pg_level level)
{
        int tdx_level = pg_level_to_tdx_sept_level(level);
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
        gpa_t gpa = gfn << PAGE_SHIFT;
        struct tdx_ex_ret ex_ret;
        u64 err;

        trace_kvm_sept_seamcall(SEAMCALL_TDH_MEM_RANGE_UNBLOCK, gpa, -1ull, tdx_level);

        err = tdh_mem_range_unblock(kvm_tdx->tdr.pa, gpa, tdx_level, &ex_ret);
        SEPT_ERR(err, &ex_ret, TDH_MEM_RANGE_UNBLOCK, kvm);
}
```



## Page fault handling in TD VM
### General KVM fault handling 
>The high-level execution flow is mostly same to normal EPT case.
>EPT violation/misconfiguration -> invoke TDP fault handler -> resolve TDP fault
>-> resume execution (or emulate MMIO). 
[[General page fault handling in KVM x86 is described here.|PAGEFAULT-HANDLING]].

### Walking mirrored private spte
As mentioned, most of page fault handling routine for the non-TD VM is utilized
for TD-VM EPT fault handling because the SPTE is repurposed for mirroring the 
S-EPT inside the TDX module. 

```cpp
 945 #define tdp_mmu_for_each_pte(_iter, _mmu, _private, _start, _end)       \
 946         for_each_tdp_pte(_iter,                                         \
 947                  to_shadow_page((_private) ? _mmu->private_root_hpa :   \
 948                                 _mmu->root.hpa),                        \
 949                 _start, _end)
```

If the faultin GPA belongs to the private address space of the TD-VM, then it 
walks private_root_hpa which is the mirrored S-EPT, instead of root.hpa. As 
before in handling normal SPT fault, iterator traverse the SPT one by one, but 
it will invoke different functions based on where the faultin GPA belongs to, 
private or not. 


```cpp
static struct kvm_mmu_page *tdp_mmu_alloc_sp(
        struct kvm_vcpu *vcpu, bool private, bool is_root)
{       
        struct kvm_mmu_page *sp;

        sp = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_page_header_cache);
        sp->spt = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_shadow_page_cache);

        if (private)
                kvm_mmu_alloc_private_sp(vcpu, sp, is_root);
        else
                kvm_mmu_init_private_sp(sp, NULL);

        return sp;
}       
```

When it encounters non-allocated spt, it should allocate new spt, but the 
allocation will little bit differ based on whether the current faultin GPA is 
private or not. If private, the newly allocated spt entry's (kvm_mmu_page)
private_sp field will be initialized with non-null pointer. If it is not a 
private, private_sp will be initialized as null pointer. 

```cpp
/* Valid sp->role.level is required. */
static inline void kvm_mmu_alloc_private_sp(
        struct kvm_vcpu *vcpu, struct kvm_mmu_page *sp, bool is_root)
{       
        if (is_root)
                sp->private_sp = KVM_MMU_PRIVATE_SP_ROOT;
        else
                sp->private_sp = kvm_mmu_memory_cache_alloc(
                        &vcpu->arch.mmu_private_sp_cache);
        /*
         * Because mmu_private_sp_cache is topped up before staring kvm page
         * fault resolving, the allocation above shouldn't fail.
         */
        WARN_ON_ONCE(!sp->private_sp);
}    
```


```cpp
1367 static int tdp_mmu_link_sp(struct kvm *kvm, struct tdp_iter *iter,
1368                            struct kvm_mmu_page *sp, bool account_nx,
1369                            bool shared)
1370 {
1371         u64 spte = make_nonleaf_spte(sp->spt, !kvm_ad_enabled());
1372         int ret = 0;                 
1373                                      
1374         if (shared) {
1375                 ret = tdp_mmu_set_spte_atomic(kvm, iter, spte);
1376                 if (ret)
1377                         return ret;
1378         } else {
1379                 tdp_mmu_set_spte(kvm, iter, spte);
1380         }
1381    
1382         spin_lock(&kvm->arch.tdp_mmu_pages_lock);
1383         list_add(&sp->link, &kvm->arch.tdp_mmu_pages);
1384         if (account_nx)
1385                 account_huge_nx_page(kvm, sp);
1386         spin_unlock(&kvm->arch.tdp_mmu_pages_lock);
1387 
1388         return 0;
1389 }  
```


### Where the set/unset is invoked?
```cpp                                                                          
3289 static int __init tdx_hardware_setup(struct kvm_x86_ops *x86_ops)          
3290 {                                                                          
......                                                                          
3306         x86_ops->set_private_spte = tdx_sept_set_private_spte;             
3307         x86_ops->drop_private_spte = tdx_sept_drop_private_spte;           
3308         x86_ops->zap_private_spte = tdx_sept_zap_private_spte;             
3309         x86_ops->unzap_private_spte = tdx_sept_unzap_private_spte;         
```

Set/Drop and Zap/Unzap operations are memory operations, so they are managed 
by the MMU code. 


**arch/x86/kvm/mmu/mmu.c**
```cpp
3539 static int __direct_map(struct kvm_vcpu *vcpu, gpa_t gpa, u32 error_code,
3540                         int map_writable, int max_level, kvm_pfn_t pfn,
3541                         bool prefault, bool is_tdp)
3542 {
......
3636         if (!is_private) {
3637                 if (!vcpu->arch.mmu->no_prefetch)
3638                         direct_pte_prefetch(vcpu, it.sptep);
3639         } else if (!WARN_ON_ONCE(ret != RET_PF_FIXED)) {
3640                 if (is_zapped_pte)
3641                         static_call(kvm_x86_unzap_private_spte)(vcpu->kvm, base_gfn, level);
3642                 else
3643                         static_call(kvm_x86_set_private_spte)(vcpu, base_gfn, level, pfn);
3644         }
```


### Move below to another article comparing remove and reclaim
TDH.MEM.PAGE.REMOVE removes a 4KB, 2MB or 1GB private page from the TD’s Secure
EPT tree. TDR.LIFECYCLE_STATE is TD_KEYS_CONFIGURED. Walk the Secure EPT based 
on the GPA operand, and find the page to be removed.


TDH_PHYMEM_PAGE_RECLAIM_LEAF
The dropping private page from TD VM is allowed only when the target TD VM is 
in TD_TEARDOWN status.



```cpp
static int __tdx_reclaim_page(unsigned long va, hpa_t pa, enum pg_level level,
			      bool do_wb, u16 hkid)
{
	struct tdx_ex_ret ex_ret;
	u64 err;

	err = tdh_phymem_page_reclaim(pa, &ex_ret);
	if (TDX_ERR(err, TDH_PHYMEM_PAGE_RECLAIM, &ex_ret))
		return -EIO;

	WARN_ON_ONCE(ex_ret.phymem_page_md.page_size !=
		     pg_level_to_tdx_sept_level(level));

	/* only TDR page gets into this path */
	if (do_wb &&
	    level == PG_LEVEL_4K) {
		err = tdh_phymem_page_wbinvd(set_hkid_to_hpa(pa, hkid));
		if (TDX_ERR(err, TDH_PHYMEM_PAGE_WBINVD, NULL))
			return -EIO;
	}

	tdx_clear_page(va, KVM_HPAGE_SIZE(level));
	return 0;
}
```
