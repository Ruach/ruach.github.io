---
layout: post
title: "TD VM Life Cycle Part 3"
categories: [Confidential Computing, Intel TDX]
---

## TD Boot Memory Setup (TDH.MEM.SEPT.ADD-TDH.MR.EXTEND)
In the previous postings, we built the meta data required for launching TD VM 
such as TDR, TDCS and VMCS of VCPU. However, to actually run code inside the TD,
we need memory pages and its mappings. We will see how TDX Module builds up the 
Secure EPT for private memories and add initial set of TD private pages using 
TDH.MEM.SEPT.ADD and TDH.MEM.PAGE.ADD, respectively. 

```cpp
2439 static int tdx_vm_ioctl(struct kvm *kvm, void __user *argp)
2440 {
......
2453         case KVM_TDX_INIT_MEM_REGION:
2454                 r = tdx_init_mem_region(kvm, &tdx_cmd);
2455                 break;
2456         case KVM_TDX_FINALIZE_VM:
2457                 r = tdx_td_finalizemr(kvm);
2458                 break;
```

### Loading TDVF to TD VM
Typically, initial pages of the TD VM contain Virtual BIOS code and data along 
with some clear pages for stacks and heap. Most of the guest TD code and data is
dynamically loaded at a later stage. Because the TDVF image is prepared by the 
user process (QEMU) and passed to the KVM, the KVM should interacts with QEMU
and TDX Module to successfully load the TDVF image to the TD VM.


```cpp
struct kvm_tdx_init_mem_region {
        __u64 source_addr;
        __u64 gpa;
        __u64 nr_pages; 
};    
```
***QEMU SIDE CODE***
```cpp
 248     for_each_fw_entry(&tdx->fw, entry) {                                   
 249         struct kvm_tdx_init_mem_region mem_region = {                      
 250             .source_addr = (__u64)entry->mem_ptr,                          
 251             .gpa = entry->address,                                         
 252             .nr_pages = entry->size / 4096,
 253         };
```

***KVM SIDE CODE***
```cpp
static int tdx_init_mem_region(struct kvm *kvm, struct kvm_tdx_cmd *cmd)
{
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
        struct kvm_tdx_init_mem_region region;
        struct kvm_vcpu *vcpu;
        struct page *page;
        u64 error_code;
        kvm_pfn_t pfn;
        int idx, ret = 0;

        /* The BSP vCPU must be created before initializing memory regions. */
        if (!atomic_read(&kvm->online_vcpus))
                return -EINVAL;

        if (cmd->flags & ~KVM_TDX_MEASURE_MEMORY_REGION)
                return -EINVAL;

        if (copy_from_user(&region, (void __user *)cmd->data, sizeof(region)))
                return -EFAULT;
        ......
```

Before initializing and loading the VCPU MMU, it first copies region information
from the user. This is the address region passed from the user process utilizing
the KVM module. The **source_addr** is the QEMU's user level address, containing 
each TDVF's section code/data. And the **gpa** is the address of TDVF section
where each section code/data should be loaded to (GPA). Note that TDVF should be 
loaded into the designated physical address of the TD-VM so that it can start 
from there. The passed HVA is used to map TDVF to HPA mapped to the HVA. 

Recall that memslot is generated for the GPA memory regions as a result of ioctl call to KVM
module from QEMU. Note that it only accepts TD private pages. When the TD-VM 
requires the shared page, it should invoke MapGPA to convert it. 



## Loading shared EPT and initializing MMU
Before loading the TDVF to TD VM memory, the MMU of the VCPU should be set up.

```cpp
static int tdx_init_mem_region(struct kvm *kvm, struct kvm_tdx_cmd *cmd)        
{     
        ......
        vcpu = kvm_get_vcpu(kvm, 0);
        if (mutex_lock_killable(&vcpu->mutex))
                return -EINTR;

        vcpu_load(vcpu);
        idx = srcu_read_lock(&kvm->srcu);

        kvm_mmu_reload(vcpu);
```


```cpp
static void vt_vcpu_load(struct kvm_vcpu *vcpu, int cpu)
{
        if (is_td_vcpu(vcpu))
                return tdx_vcpu_load(vcpu, cpu);

        return vmx_vcpu_load(vcpu, cpu);
}
```

```cpp
void tdx_vcpu_load(struct kvm_vcpu *vcpu, int cpu)
{
        struct vcpu_tdx *tdx = to_tdx(vcpu);

        vmx_vcpu_pi_load(vcpu, cpu);
        if (vcpu->cpu == cpu)
                return;

        tdx_flush_vp_on_cpu(vcpu);

        local_irq_disable();
        /*
         * Pairs with the smp_wmb() in tdx_disassociate_vp() to ensure
         * vcpu->cpu is read before tdx->cpu_list.
         */
        smp_rmb();

        list_add(&tdx->cpu_list, &per_cpu(associated_tdvcpus, cpu));
        local_irq_enable();
}

```


### Reload MMU (Shared EPT initialization) 
The primary job of reloading MMU is initializing the SPT, especially when the 
root_hpa is set as INVALID_PAGE. Because the root_hpa was touched when the MMU 
is initialized, but the root of the SPT has not been initialized, so reload func
initializes the SPT for VM. 

```cpp
5732 int kvm_mmu_load(struct kvm_vcpu *vcpu)
5733 {
5734         int r;
5735 
5736         r = mmu_topup_memory_caches(vcpu, !vcpu->arch.mmu->direct_map);
5737         if (r)
5738                 goto out;
5739         r = mmu_alloc_special_roots(vcpu);
5740         if (r)              
5741                 goto out;
5742         if (vcpu->arch.mmu->direct_map)
5743                 r = mmu_alloc_direct_roots(vcpu);
5744         else
5745                 r = mmu_alloc_shadow_roots(vcpu); 
5746         if (r)
5747                 goto out;
5748 
5749         kvm_mmu_sync_roots(vcpu);
5750 
5751         kvm_mmu_load_pgd(vcpu);
5752         static_call(kvm_x86_tlb_flush_current)(vcpu);
5753 out:   
5754         return r;
5755 }
```

As we covered before, about how the SPT is allocated, the mmu_alloc_direct_roots 
allocates the SPT for shared pages and private pages. Please refer to [[]] for 
details. 

```cpp
109 static inline void kvm_mmu_load_pgd(struct kvm_vcpu *vcpu)
110 {        
111         u64 root_hpa = vcpu->arch.mmu->root_hpa;
112 
113         if (!VALID_PAGE(root_hpa))
114                 return;
115 
116         static_call(kvm_x86_load_mmu_pgd)(vcpu, root_hpa,
117                                           vcpu->arch.mmu->shadow_root_level);
118 } 
```

```cpp
 491 static void vt_load_mmu_pgd(struct kvm_vcpu *vcpu, hpa_t root_hpa,
 492                             int pgd_level)
 493 {
 494         if (is_td_vcpu(vcpu))
 495                 return tdx_load_mmu_pgd(vcpu, root_hpa, pgd_level);
 496 
 497         vmx_load_mmu_pgd(vcpu, root_hpa, pgd_level);
 498 }
```

```cpp
1602 static void tdx_load_mmu_pgd(struct kvm_vcpu *vcpu, hpa_t root_hpa,
1603                              int pgd_level)
1604 {
1605         td_vmcs_write64(to_tdx(vcpu), SHARED_EPT_POINTER, root_hpa & PAGE_MASK);
1606 }
```

Because current VCPU belongs to the TD-VM, the SPT used for shared pages should 
be set to **shared EPTP**. For vanilla VM, only the EPT_POINTER exists. Because 
TD-VM also utilize the shared EPT, which is identical to EPT_POINTER in vanilla 
VM, it should be set up during the MMU-setup. Note that the private EPTP can be
set only through SEPT related SEAMCALLs. 

### Adding page to TD VM
Because KVM MMU is initialized and the shared EPTP is correctly set to the VMCS 
of TD-VCPU, we can finally add some memories to the TD-VM. Let's go back to the 
tdx_init_mem_region function. 

Note that the tdvf binary is already loaded into the QEMU address space 
dedicated for the TD-VM, but to be utilized as private pages of the TD-VM, it 
should be added to the target TD-VM through the SEAMCALL.


## Load the TDVF images into TD memory 
```cpp
static int tdx_init_mem_region(struct kvm *kvm, struct kvm_tdx_cmd *cmd)
{
    struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
    struct kvm_tdx_init_mem_region region;
    struct kvm_vcpu *vcpu;
    struct page *page;
    u64 error_code;
    kvm_pfn_t pfn;
    int idx, ret = 0;
    ......
    while (region.nr_pages) {
            if (signal_pending(current)) {
                    ret = -ERESTARTSYS;
                    break;
            }    

            if (need_resched())
                    cond_resched();


            /* Pin the source page. */
            ret = get_user_pages_fast(region.source_addr, 1, 0, &page);
            if (ret < 0) 
                    break;
            if (ret != 1) { 
                    ret = -ENOMEM;
                    break;
            }    

            kvm_tdx->source_pa = pfn_to_hpa(page_to_pfn(page)) |
                                 (cmd->flags & KVM_TDX_MEASURE_MEMORY_REGION);

            /* TODO: large page support. */
            error_code = TDX_SEPT_PFERR;
            error_code |= (PG_LEVEL_4K << PFERR_LEVEL_START_BIT) &
                    PFERR_LEVEL_MASK;
            pfn = kvm_mmu_map_tdp_page(vcpu, region.gpa, error_code,
                                       PG_LEVEL_4K);
            if (is_error_noslot_pfn(pfn) || kvm->vm_bugged)
                    ret = -EFAULT;
            else 
                    ret = 0; 

            put_page(page);
            if (ret)
                    break;

            region.source_addr += PAGE_SIZE;
            region.gpa += PAGE_SIZE;
            region.nr_pages--;
    }    
```

Because the passed memory region belongs to user process, it should be pinned 
by the KVM module first before being copied to TD-VM pages. Note that it invokes 
function get_user_pages_fast with **region.source_addr which is the HVA** of the
QEMU. Also the function assumes that all page table associated with user address
is mapped. Unless the page table has not been resolved yet to translate passed 
user space address to HPA, KVM just returns. After the pinning, each page should
be mapped through the kvm_mmu_map_tdp_page. Note that the pinned page's physical
address is stored in kvm_tdx->source_pa. This page address will be used later to
copy the content from host page to TD VM page by __tdx_sept_set_private_spte.

### kvm_mmu_map_tdp_page
We now have pinned HVA and its physical address HPA. Also, we have target GPA
where the TDVF should be loaded into. Let's load the memory!

```cpp
kvm_pfn_t kvm_mmu_map_tdp_page(struct kvm_vcpu *vcpu, gpa_t gpa,
                               u32 error_code, int max_level)
{
        int r;
        struct kvm_page_fault fault = (struct kvm_page_fault) {
                .addr = gpa,
                .error_code = error_code,
                .exec = error_code & PFERR_FETCH_MASK,
                .write = error_code & PFERR_WRITE_MASK,
                .present = error_code & PFERR_PRESENT_MASK,
                .rsvd = error_code & PFERR_RSVD_MASK,
                .user = error_code & PFERR_USER_MASK,
                .prefetch = false,
                .is_tdp = true,
                .nx_huge_page_workaround_enabled = is_nx_huge_page_enabled(),
                .is_private = kvm_is_private_gpa(vcpu->kvm, gpa),
        };      

        if (mmu_topup_memory_caches(vcpu, false))
                return KVM_PFN_ERR_FAULT;

        /*
         * Loop on the page fault path to handle the case where an mmu_notifier
         * invalidation triggers RET_PF_RETRY.  In the normal page fault path,
         * KVM needs to resume the guest in case the invalidation changed any
         * of the page fault properties, i.e. the gpa or error code.  For this
         * path, the gpa and error code are fixed by the caller, and the caller
         * expects failure if and only if the page fault can't be fixed.
         */             
        do {    
                fault.max_level = max_level;
                fault.req_level = PG_LEVEL_4K;
                fault.goal_level = PG_LEVEL_4K;
                r = direct_page_fault(vcpu, &fault);
        } while (r == RET_PF_RETRY && !is_error_noslot_pfn(fault.pfn));
        return fault.pfn;
}               
```

Although there is no page fault because we haven't executed the VCPU yet in 
TD-VM side. However, it invokes the direct_page_fault function implementing the
page fault handling as if the EPT violation happens on the GPA that should be 
initialized. Therefore, direct_page_fault handles injected emulated page fault
and allocates all SPTE required for mapping target GPA to HPA. Also note that
the fault-in address is set as gpa which is the GPA of TD VM where the TDVF 
memory will be copied into later. After the injected page fault is resolved, the
TD VM can access the TDVF by the gpa through the generated mapping. 


```cpp
static int direct_page_fault(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault)
{
        bool is_tdp_mmu_fault = is_tdp_mmu(vcpu->arch.mmu);

        unsigned long mmu_seq;
        int r;

        fault->gfn = gpa_to_gfn(fault->addr) & ~kvm_gfn_shared_mask(vcpu->kvm);
        fault->slot = kvm_vcpu_gfn_to_memslot(vcpu, fault->gfn);
        ......
        if (is_tdp_mmu_fault)
                r = kvm_tdp_mmu_map(vcpu, fault);
        else
                r = __direct_map(vcpu, fault);
```

Based on the mmu configuration of vcpu, it invokes kvm_tdp_mmu_map or 
__direct_map function to handle the fault. 

```cpp
static int __direct_map(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault)
{
        struct kvm_shadow_walk_iterator it;
        gfn_t base_gfn = fault->gfn;
        bool is_private = fault->is_private;
        bool is_zapped_pte;
        unsigned int pte_access;
        int ret;
	......
        __direct_populate_nonleaf(vcpu, fault, &it, &base_gfn);
```

To resolve this TDX page fault, we needs to handle two important things. The 
first is generating S-EPT mapping. The second is adding page to TD-VM. 

![PRIVATE_PAGE](/assets/img/TDX//ADD_PRIVATE_PAGE.png)

## Add S-EPT for private page translation (TDH_MEM_SEPT_ADD)
To translate private page belong to TD-VM, it needs SPTE for non-leaf and leaf.
Whether it is non-leaf or not, for private pages, it needs to invoke SEAMCALL,
TDH_MEM_SEPT_ADD because SPTE for private pages are maintained by the TDX module.

```cpp
static void __direct_populate_nonleaf(struct kvm_vcpu *vcpu,
                                struct kvm_page_fault *fault,
                                struct kvm_shadow_walk_iterator *itp,
                                gfn_t *base_gfnp)
{
        bool is_private = fault->is_private;
        struct kvm_shadow_walk_iterator it;
        struct kvm_mmu_page *sp;
        gfn_t base_gfn;

        if (kvm_gfn_shared_mask(vcpu->kvm))
                fault->max_level = min(
                        fault->max_level,
                        max_level_of_valid_page_type(fault->gfn, fault->slot));
        /*
         * Cannot map a private page to higher level if smaller level mapping
         * exists. It can be promoted to larger mapping later when all the
         * smaller mapping are there.
         */
        if (is_private) {
                for_each_shadow_entry(vcpu, fault->addr, it) {
                        if (is_shadow_present_pte(*it.sptep)) {
                                if (!is_last_spte(*it.sptep, it.level) &&
                                        fault->max_level >= it.level)
                                        fault->max_level = it.level - 1;
                        } else {
                                break;
                        }
                }
        }

        kvm_mmu_hugepage_adjust(vcpu, fault);

        trace_kvm_mmu_spte_requested(fault);
        for_each_shadow_entry(vcpu, fault->addr, it) {
                /*
                 * We cannot overwrite existing page tables with an NX
                 * large page, as the leaf could be executable.
                 */
                if (fault->nx_huge_page_workaround_enabled)
                        disallowed_hugepage_adjust(fault, *it.sptep, it.level);

                base_gfn = fault->gfn & ~(KVM_PAGES_PER_HPAGE(it.level) - 1);
                if (it.level == fault->goal_level)
                        break;

                drop_large_spte(vcpu, it.sptep);
                if (is_shadow_present_pte(*it.sptep))
                        continue;

                sp = kvm_mmu_get_page(vcpu, base_gfn, it.addr, it.level - 1,
                                      true, ACC_ALL, is_private);

                link_shadow_page(vcpu, it.sptep, sp);
                if (fault->is_tdp && fault->huge_page_disallowed &&
                    fault->req_level >= it.level)
                        account_huge_nx_page(vcpu->kvm, sp);
                if (is_private)
                        kvm_mmu_link_private_sp(vcpu->kvm, sp);
        }

        *itp = it;
        if (base_gfnp)
                *base_gfnp = base_gfn;
}
```

### Walking shadow page tables 
The main loop body of page table walking is done by for_each_shadow_entry macro.
Although the TDX Module manages S-EPT, the host VMM also maintains the mirror of
the S-EPT in host memory so that it can reduce the burden of TDX Module. For 
example, to add S-EPT for one physical page, VMM can ask the TDX Module to walk
the secure page table inside the TDX Module, but host VMM does walk the mirrored
S-EPT on behalf of the TDX Module and send request to the TDX Module for S-EPT
insertion through the SEAMCALL TDH_MEM_SEPT_ADD.

```cpp
#define for_each_shadow_entry(_vcpu, _addr, _walker)            \
        for (shadow_walk_init(&(_walker), _vcpu, _addr);        \
             shadow_walk_okay(&(_walker));                      \
             shadow_walk_next(&(_walker)))
```

```cpp
static void shadow_walk_init(struct kvm_shadow_walk_iterator *iterator,
                             struct kvm_vcpu *vcpu, u64 addr)
{
        hpa_t root;

        if (tdp_enabled && kvm_is_private_gpa(vcpu->kvm, addr))
                root = vcpu->arch.mmu->private_root_hpa;
        else
                root = vcpu->arch.mmu->root.hpa;

        shadow_walk_init_using_root(iterator, vcpu, root, addr);
}
```

Based on whether the fault belongs to private or not, it selects different root
page table, private_root_hpa or root.hpa, respectively. 

```cpp
static void shadow_walk_init_using_root(struct kvm_shadow_walk_iterator *iterator,
                                        struct kvm_vcpu *vcpu, hpa_t root,
                                        u64 addr)
{
        iterator->addr = addr;
        iterator->shadow_addr = root;
        iterator->level = vcpu->arch.mmu->root_role.level;

        if (iterator->level >= PT64_ROOT_4LEVEL &&
            vcpu->arch.mmu->cpu_role.base.level < PT64_ROOT_4LEVEL &&
            !vcpu->arch.mmu->root_role.direct)
                iterator->level = PT32E_ROOT_LEVEL;

        if (iterator->level == PT32E_ROOT_LEVEL) {
                /*
                 * prev_root is currently only used for 64-bit hosts. So only
                 * the active root_hpa is valid here.
                 */
                BUG_ON(root != vcpu->arch.mmu->root.hpa);

                iterator->shadow_addr
                        = vcpu->arch.mmu->pae_root[(addr >> 30) & 3];
                iterator->shadow_addr &= PT64_BASE_ADDR_MASK;
                --iterator->level;
                if (!iterator->shadow_addr)
                        iterator->level = 0;
        }
}
```

After setting up the root page table, it also initialize the iterator based 
on the MMU settings, and page fault address.

```cpp
static bool shadow_walk_okay(struct kvm_shadow_walk_iterator *iterator)
{
        if (iterator->level < PG_LEVEL_4K)
                return false;

        iterator->index = SHADOW_PT_INDEX(iterator->addr, iterator->level);
        iterator->sptep = ((u64 *)__va(iterator->shadow_addr)) + iterator->index;
        return true;
}
```
After one iteration finishes, it checks if it can further go down, until leaf.
The addr field of the iterator points to the fault-in address. The index of the 
next level page table is calculated based on current level and fault-in addr.
Also, the sptep field points to the non-leaf spte or PTE of this level. Walking 
continues until the level of iterator reaches the leaf page table entry 
(PG_LEVEL_4K). 

```cpp
static void shadow_walk_next(struct kvm_shadow_walk_iterator *iterator)
{
        __shadow_walk_next(iterator, *iterator->sptep);
}

static void __shadow_walk_next(struct kvm_shadow_walk_iterator *iterator,
                               u64 spte)
{
        if (!is_shadow_present_pte(spte) || is_last_spte(spte, iterator->level)) {
                iterator->level = 0;
                return;
        }

        iterator->shadow_addr = spte & PT64_BASE_ADDR_MASK;
        --iterator->level;
}
```

The **shadow_addr** member field of the iterator points to the root address of 
the next level page table or the leaf PTE. 


### Set-up S-EPT
Before we add the S-EPT associated with the TDVF image, non-leaf S-EPT entries 
should be added into the TDX memories so that the mapping from the root to the 
leaf for the S-EPT will be populated. As a result private pages of the TD-VM can
be translated into the HPA smoothly without incurring any page faults. 

```cpp
        for_each_shadow_entry(vcpu, fault->addr, it) {
                /*
                 * We cannot overwrite existing page tables with an NX
                 * large page, as the leaf could be executable.
                 */
                if (fault->nx_huge_page_workaround_enabled)
                        disallowed_hugepage_adjust(fault, *it.sptep, it.level);

                base_gfn = fault->gfn & ~(KVM_PAGES_PER_HPAGE(it.level) - 1);
                if (it.level == fault->goal_level)
                        break;

                drop_large_spte(vcpu, it.sptep);
                if (is_shadow_present_pte(*it.sptep))
                        continue;

                sp = kvm_mmu_get_page(vcpu, base_gfn, it.addr, it.level - 1,
                                      true, ACC_ALL, is_private);

                link_shadow_page(vcpu, it.sptep, sp);
                if (fault->is_tdp && fault->huge_page_disallowed &&
                    fault->req_level >= it.level)
                        account_huge_nx_page(vcpu->kvm, sp);
                if (is_private)
                        kvm_mmu_link_private_sp(vcpu->kvm, sp);
        }
```

Above loop walks the private page table until the current level matches with the
level of fault-in page. While the sptep entry presents, it continues walking and
allocate one page when it does not present. kvm_mmu_get_page function allocates
new spte and link_shadow_page links the generated page to sptep of current level.
Detailed implementation is already covered in [[]]. Let's see what difference 
has been introduced due to TDX. 

```cpp
static struct kvm_mmu_page *kvm_mmu_get_page(struct kvm_vcpu *vcpu,
                                             gfn_t gfn,
                                             gva_t gaddr,
                                             unsigned level,
                                             int direct,
                                             unsigned int access,
                                             unsigned int private)
{
        ......
	sp = kvm_mmu_alloc_page(vcpu, direct, private);

        sp->gfn = gfn; 
        sp->role = role;                                 
        /* kvm_mmu_alloc_private_sp() requires valid role. */
        if (private)
                kvm_mmu_alloc_private_sp(
                        vcpu, sp, level == vcpu->arch.mmu->root_role.level);
```

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

kvm_mmu_get_page allocates kvm_mmu_page. The spte page is allocated by the 
kvm_mmu_alloc_private_sp function if it is private page. One thing added for 
private SPTE is **private_sp** field of the kvm_mmu_mpage. To add new S-EPT, 
through the SEAMCALL, host KVM should provide memory page to TDX so that it can
use **this page to fill out S-EPT**. If this is not a root, 
kvm_mmu_memory_cache_alloc function allocates page for S-EPT.

After the SPTE page is allocated, link_shadow_page links allocated page in the 
**host KVM side**. Recall that KVM maintains a mirrored SPTE for private pages. 
However, we do need the S-EPT entry in the TDX side also so that the hardware 
based translation smoothly translate TD-VM private pages to the HPA during its 
execution. To this end, it additionally invokes the func kvm_mmu_link_private_sp
and add S-EPT page **at TDX side** through the TDH_MEM_SEPT_ADD. 


```cpp
static inline int kvm_mmu_link_private_sp(struct kvm *kvm,
                                        struct kvm_mmu_page *sp) 
{                   
        /* Link this sp to its parent spte.  + 1 for parent spte. */
        return static_call(kvm_x86_link_private_sp)(
                kvm, sp->gfn, sp->role.level + 1, sp->private_sp);
}       


static int tdx_sept_link_private_sp(struct kvm *kvm, gfn_t gfn,
                                    enum pg_level level, void *sept_page)
{       
        int tdx_level = pg_level_to_tdx_sept_level(level);
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm); 
        gpa_t gpa = gfn_to_gpa(gfn);
        hpa_t hpa = __pa(sept_page);
        struct tdx_module_output out;
        u64 err;

        spin_lock(&kvm_tdx->seamcall_lock);
        err = tdh_mem_sept_add(kvm_tdx->tdr.pa, gpa, tdx_level, hpa, &out);
        spin_unlock(&kvm_tdx->seamcall_lock);
        if (KVM_BUG_ON(err, kvm)) {
                pr_tdx_error(TDH_MEM_SEPT_ADD, err, &out);
                return -EIO;
        }                          

        return 0;
}       
```



## Add private pages (TDH_MEM_PAGE_ADD)
```cpp
static int __direct_map(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault)
{                               
        struct kvm_shadow_walk_iterator it;                                     
        gfn_t base_gfn = fault->gfn;                                            
        bool is_private = fault->is_private;                                    
        bool is_zapped_pte;                                                     
        unsigned int pte_access;                                                
        int ret;         
        ......
        if (!is_private) {
                if (!vcpu->arch.mmu->no_prefetch)
                        direct_pte_prefetch(vcpu, it.sptep);
        } else if (!WARN_ON_ONCE(ret != RET_PF_FIXED)) {
                if (is_zapped_pte)
                        static_call(kvm_x86_unzap_private_spte)(
                                vcpu->kvm, base_gfn, it.level);
                else
                        static_call(kvm_x86_set_private_spte)(
                                vcpu->kvm, base_gfn, it.level, fault->pfn);
        }

        return ret;
}
```
After resolving S-EPT mappings, it returns to the __direct_map and invokes 
kvm_x86_set_private_spte function to covert host VMM pages containing TDVF into
private memory of the TD VM.


```cpp
static void __tdx_sept_set_private_spte(struct kvm *kvm, gfn_t gfn,
                                        enum pg_level level, kvm_pfn_t pfn)
{       
        int tdx_level = pg_level_to_tdx_sept_level(level);
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
        hpa_t hpa = pfn_to_hpa(pfn);
        gpa_t gpa = gfn_to_gpa(gfn);
        struct tdx_module_output out;
        hpa_t source_pa;
        u64 err;
        int i;
        
        if (WARN_ON_ONCE(is_error_noslot_pfn(pfn) || kvm_is_reserved_pfn(pfn)))
                return;
        
        /* Only support 4KB and 2MB pages */
        if (KVM_BUG_ON(level > PG_LEVEL_2M, kvm))
                return;
                
        /* To prevent page migration, do nothing on mmu notifier. */
        for (i = 0; i < KVM_PAGES_PER_HPAGE(level); i++)
                get_page(pfn_to_page(pfn + i));
                
        /* Build-time faults are induced and handled via TDH_MEM_PAGE_ADD. */
        if (likely(is_td_finalized(kvm_tdx))) {
                /*
                 * For now only 4K and 2M pages are tested by KVM MMU.
                 * TODO: support/test 1G large page.
                 */
                if (KVM_BUG_ON(level > PG_LEVEL_2M, kvm))
                        return;

                err = tdh_mem_page_aug(kvm_tdx->tdr.pa, gpa, tdx_level, hpa, &out);
                if (KVM_BUG_ON(err, kvm)) {
                        pr_tdx_error(TDH_MEM_PAGE_AUG, err, &out);
                        tdx_unpin(kvm, gfn, pfn, level);
                }
                return;
        }

        /* KVM_INIT_MEM_REGION, tdx_init_mem_region(), supports only 4K page. */
        if (KVM_BUG_ON(level != PG_LEVEL_4K, kvm))
                return;

        /*
         * In case of TDP MMU, fault handler can run concurrently.  Note
         * 'source_pa' is a TD scope variable, meaning if there are multiple
         * threads reaching here with all needing to access 'source_pa', it
         * will break.  However fortunately this won't happen, because below
         * TDH_MEM_PAGE_ADD code path is only used when VM is being created
         * before it is running, using KVM_TDX_INIT_MEM_REGION ioctl (which
         * always uses vcpu 0's page table and protected by vcpu->mutex).
         */
        if (KVM_BUG_ON(kvm_tdx->source_pa == INVALID_PAGE, kvm)) {
                tdx_unpin(kvm, gfn, pfn, level);
                return;
        }

        source_pa = kvm_tdx->source_pa & ~KVM_TDX_MEASURE_MEMORY_REGION;

        err = tdh_mem_page_add(kvm_tdx->tdr.pa, gpa, tdx_level, hpa, source_pa, &out);
        if (KVM_BUG_ON(err, kvm)) {
                pr_tdx_error(TDH_MEM_PAGE_ADD, err, &out);
                tdx_unpin(kvm, gfn, pfn, level);
        } else if ((kvm_tdx->source_pa & KVM_TDX_MEASURE_MEMORY_REGION))
                tdx_measure_page(kvm_tdx, gpa, KVM_HPAGE_SIZE(level));

        kvm_tdx->source_pa = INVALID_PAGE;
}
```

If the target TD-VM has been already finalized, the page can only be inserted 
as the TDH_MEM_PAGE_AUG SEAMCALL, but if not, TDH_MEM_PAGE_ADD SEAMCALL allows 
it to have new private page. 

![MEM_PAGE_ADD](/assets/img/TDX//TDH_MEM_PAGE_ADD.png)

This SEAMCALL requires four important information about the addresses to add new
page to the TD VM. The first is the EPT mapping information which we already
have as a result of TDH_MEM_SEPT_ADD. The second is HPA of the TDR page. The 
third one is HPA of the target page to be added to the TD VM. And the last one 
is the address of the source page containing data/code. Note that the source_pa
points to the QEMU page containing TDVF image. gpa is the EPT mapping address 
inside the TDX Module. Recall that the main loop for S-EPT updates base_gfn to 
the updates S-EPT entry. hpa is the destination page that will be added to the 
TD VM.

## KVM_TDX_FINALIAZE_VM
After the initial set of pages is added and extended, the VMM can finalize the 
TD measurement using the TDH.MR.FINALIZE SEAMCALL. After this SEAMCALL returns 
successfully, its measurement cannot be modified anymore (except the run-time
measurement registers). Also, the TD VCPUs can enter to the TD VM through the 
TDH.VP.ENTER.


## Misc
### static_call 
**arch/x86/kvm/x86.c**
```cpp
  131 #define KVM_X86_OP(func)                                             \
  132         DEFINE_STATIC_CALL_NULL(kvm_x86_##func,                      \
  133                                 *(((struct kvm_x86_ops *)0)->func));
  134 #define KVM_X86_OP_NULL KVM_X86_OP
  135 #include <asm/kvm-x86-ops.h>
```

**asm/kvm-x86-ops.h**
```cpp
/*
 * KVM_X86_OP() and KVM_X86_OP_NULL() are used to help generate
 * "static_call()"s. They are also intended for use when defining
 * the vmx/svm kvm_x86_ops. KVM_X86_OP() can be used for those
 * functions that follow the [svm|vmx]_func_name convention.
 * KVM_X86_OP_NULL() can leave a NULL definition for the
 * case where there is no definition or a function name that
 * doesn't match the typical naming convention is supplied.
 */
KVM_X86_OP_NULL(hardware_enable)
KVM_X86_OP_NULL(hardware_disable)
KVM_X86_OP_NULL(hardware_unsetup)
KVM_X86_OP_NULL(cpu_has_accelerated_tpr)
```

### KVM_INTEL_TDX_SEAM_BACKDOOR
>This kernel config enables Trusted Domain Extensions backdoor interface for development.
>Backdoor interface provides raw interface to call TDX SEAM module for user land. This is 
>only for development so that KVM doesn't guarantee any integrity like cache coherency. 
>To enable this feature, also pass tdx_seam_backdoor to the command line.


https://lwn.net/Articles/827925/
>SEV currently needs to pin guest memory as it doesn't support migrating
>encrypted pages.  Introduce a framework in KVM's MMU to support pinning
>pages on demand without requiring additional memory allocations, and with
>(somewhat hazy) line of sight toward supporting more advanced features for
>encrypted guest memory, e.g. host page migration.
>The idea is to use a software available bit in the SPTE to track that a
>page has been pinned.  The decision to pin a page and the actual pinning
>managment is handled by vendor code via kvm_x86_ops hooks.

Introduce a helper to directly (pun intended) fault-in a TDP page
without having to go through the full page fault path.  This allows
TDX to get the resulting pfn and also allows the RET_PF_* enums to
stay in mmu.c where they belong.


