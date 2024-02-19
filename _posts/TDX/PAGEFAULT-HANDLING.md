
# EPT violation exit and handle
The logistics of KVM's page fault handling is like below: 
__vmx_handle_exit -> handle_ept_violation -> __vmx_handle_ept_violation ->
kvm_mmu_page_fault -> kvm_mmu_do_page_fault -> mmu.page_fault(), 
kvm_tdp_page_fault (when tdp is enabled) -> direct_page_fault

## EPT violation exit reason interpretation 
```cpp
static inline int __vmx_handle_ept_violation(struct kvm_vcpu *vcpu, gpa_t gpa,
                                             unsigned long exit_qualification,
                                             int err_page_level)
{
        u64 error_code;
        
        /* Is it a read fault? */
        error_code = (exit_qualification & EPT_VIOLATION_ACC_READ)
                     ? PFERR_USER_MASK : 0;
        /* Is it a write fault? */
        error_code |= (exit_qualification & EPT_VIOLATION_ACC_WRITE)
                      ? PFERR_WRITE_MASK : 0;
        /* Is it a fetch fault? */
        error_code |= (exit_qualification & EPT_VIOLATION_ACC_INSTR)
                      ? PFERR_FETCH_MASK : 0;
        /* ept page table entry is present? */
        error_code |= (exit_qualification &
                       (EPT_VIOLATION_READABLE | EPT_VIOLATION_WRITABLE |
                        EPT_VIOLATION_EXECUTABLE))
                      ? PFERR_PRESENT_MASK : 0;
        
        error_code |= (exit_qualification & EPT_VIOLATION_GVA_TRANSLATED) != 0 ?
               PFERR_GUEST_FINAL_MASK : PFERR_GUEST_PAGE_MASK;

        if (err_page_level > 0)
                error_code |= (err_page_level << PFERR_LEVEL_START_BIT) & PFERR_LEVEL_MASK;

        return kvm_mmu_page_fault(vcpu, gpa, error_code, NULL, 0);
}
```

exit_qualification can be retrieved from the VMCS structure. Based on the exit
reasons, different bits are set, so they should be interpreted by the VMM side 
to handle EPT violation properly.


```cpp
static int direct_page_fault(struct kvm_vcpu *vcpu, gpa_t gpa, u32 error_code,
                             bool prefault, int max_level, bool is_tdp,
                             kvm_pfn_t *pfn)
{
        bool is_tdp_mmu_fault = is_tdp_mmu(vcpu->arch.mmu);
        bool write = error_code & PFERR_WRITE_MASK;
        bool map_writable;

        gfn_t gfn = vcpu_gpa_to_gfn_unalias(vcpu, gpa);
......
        r = fast_page_fault(vcpu, gpa, error_code);
        if (r != RET_PF_INVALID)
                return r;
......
        if (kvm_faultin_pfn(vcpu, prefault, gfn, gpa, pfn, &hva,
                         write, &map_writable, &r))
......
        if (is_tdp_mmu_fault)
                r = kvm_tdp_mmu_map(vcpu, gpa, error_code, map_writable, max_level,
                                    *pfn, prefault);
        else
                r = __direct_map(vcpu, gpa, error_code, map_writable, max_level,
                                 *pfn, prefault, is_tdp);
}
```
direct_page_fault consists of two main parts: 1. Translate faultin gpa -> hva 
-> hpa 2. Resolve page fault. gpa is the address that cause EPT fault, and 
error_code describe the reason of EPT fault such as read/write fault. pfn param
is the address that caused the VM EXIT, due to EPT violation. The max_level is 
vcpu->kvm->arch.tdp_max_page_level which means the maximum level of SPT.

# Faultin GPA ->(***memslot***) -> HVA -> (***host page table***) -> HPA
When EPT fault happens, only information we have is faultin GPT address. 
Remember that the GPT is not 1:1 mapped to host virtual address. Therefore, we 
need to translate GPT to HVA and walk host page table to get HPA mapped to HVA.
After retrieving the HPA, we can set the EPT table so that the faulting GPA can 
be translated into HPA that we find as a result of host page table walk. 

## GPA -> HVA
### Memslot translates GPA -> HVA
The **kvm_faultin_pfn** function resolves GPA -> HVA mapping and pin the HVA.
To translate GPA to HVA, the memslot instance associated with the faultin GPA
is required. To retrieve associated memslot, **kvm_faultin_pfn** function 
invokes kvm_vcpu_gfn_to_memslot. 


```cpp
struct kvm_memory_slot *kvm_vcpu_gfn_to_memslot(struct kvm_vcpu *vcpu, gfn_t gfn)
{
        struct kvm_memslots *slots = kvm_vcpu_memslots(vcpu);
        struct kvm_memory_slot *slot;
        int slot_index;

        slot = try_get_memslot(slots, vcpu->last_used_slot, gfn);
        if (slot)
                return slot;

        /*
         * Fall back to searching all memslots. We purposely use
         * search_memslots() instead of __gfn_to_memslot() to avoid
         * thrashing the VM-wide last_used_index in kvm_memslots.
         */
        slot = search_memslots(slots, gfn, &slot_index);
        if (slot) {
                vcpu->last_used_slot = slot_index;
                return slot;
        }

        return NULL;
}
```
kvm_vcpu_gfn_to_memslot retrieves the memslot associated with the faulted gfn.

```cpp
static bool kvm_faultin_pfn(struct kvm_vcpu *vcpu, bool prefault, gfn_t gfn,
                         gpa_t cr2_or_gpa, kvm_pfn_t *pfn, hva_t *hva,
                         bool write, bool *writable, int *r)
{
        struct kvm_memory_slot *slot = kvm_vcpu_gfn_to_memslot(vcpu, gfn);
......
        async = false;
        *pfn = __gfn_to_pfn_memslot(slot, gfn, false, &async,
                                    write, writable, hva);
        if (!async)
                return false; /* *pfn has correct page already */

        if (!prefault && kvm_can_do_async_pf(vcpu)) {
                trace_kvm_try_async_get_page(cr2_or_gpa, gfn);
                if (kvm_find_async_pf_gfn(vcpu, gfn)) {
                        trace_kvm_async_pf_doublefault(cr2_or_gpa, gfn);
                        kvm_make_request(KVM_REQ_APF_HALT, vcpu);
                        goto out_retry;
                } else if (kvm_arch_setup_async_pf(vcpu, cr2_or_gpa, gfn))
                        goto out_retry;
        }

        *pfn = __gfn_to_pfn_memslot(slot, gfn, false, NULL,
                                    write, writable, hva);

out_retry:
        *r = RET_PF_RETRY;
        return true;
}
```

After retrieving the memslot, it invokes __gfn_to_pfn_memslot function to 
translate the gfn -> hva -> pfn. 

```cpp
kvm_pfn_t __gfn_to_pfn_memslot(struct kvm_memory_slot *slot, gfn_t gfn,
                               bool atomic, bool *async, bool write_fault,
                               bool *writable, hva_t *hva)
{
        unsigned long addr = __gfn_to_hva_many(slot, gfn, NULL, write_fault);

        if (hva)
                *hva = addr;

        if (addr == KVM_HVA_ERR_RO_BAD) { 
                if (writable)      
                        *writable = false;
                return KVM_PFN_ERR_RO_FAULT;
        }                   

        if (kvm_is_error_hva(addr)) {
                if (writable)
                        *writable = false;
                return KVM_PFN_NOSLOT;
        }
                                      
        /* Do not map writable pfn in the readonly memslot. */
        if (writable && memslot_is_readonly(slot)) {
                *writable = false;
                writable = NULL;
        } 

        return hva_to_pfn(addr, atomic, async, write_fault,
                          writable);
}
```

Using memslot, __gfn_to_hva_many function returns the hva address mapped to 
faulted gfn. Also, hva_to_pfn function pins the hva and returns the pfn mapped 
to the hva. Note that the HVA belongs to user process, so it should be pinned 
by the kernel not to allow kernel switch HPA mapped to HVA.

## HVA -> HPA
### Walking host page table to pin HVA and locate HPA
Currently, we have information about faultin GPA and its HVA. We need HPA
mapped to the HVA.

```cpp
static kvm_pfn_t hva_to_pfn(unsigned long addr, bool atomic, bool *async,
                        bool write_fault, bool *writable)
{
        struct vm_area_struct *vma;
        kvm_pfn_t pfn = 0;
        int npages, r;

        /* we can do it either atomically or asynchronously, not both */
        BUG_ON(atomic && async);

        if (hva_to_pfn_fast(addr, write_fault, writable, &pfn))
                return pfn;

        if (atomic)
                return KVM_PFN_ERR_FAULT;

        npages = hva_to_pfn_slow(addr, async, write_fault, writable, &pfn);
        if (npages == 1)
                return pfn;

        mmap_read_lock(current->mm);
        if (npages == -EHWPOISON ||
              (!async && check_user_page_hwpoison(addr))) {
                pfn = KVM_PFN_ERR_HWPOISON;
                goto exit;
        }

retry:
        vma = vma_lookup(current->mm, addr);

        if (vma == NULL)
                pfn = KVM_PFN_ERR_FAULT;
        else if (vma->vm_flags & (VM_IO | VM_PFNMAP)) {
                r = hva_to_pfn_remapped(vma, addr, async, write_fault, writable, &pfn);
                if (r == -EAGAIN)
                        goto retry;
                if (r < 0)
                        pfn = KVM_PFN_ERR_FAULT;
        } else {
                if (async && vma_is_valid(vma, write_fault))
                        *async = true;
                pfn = KVM_PFN_ERR_FAULT;
        }
exit:
        mmap_read_unlock(current->mm);
        return pfn;
}

The addr parameter is host virtual address which maps memory to the guest. The 
async indicates whether it needs to wait IO complete if the host page is not 
in the memory. The write_fault means whether it requires a writable host page.
The writable means whether it allows to map a writable host page when the 
write_fault is set as false. 

```cpp
static bool hva_to_pfn_fast(unsigned long addr, bool write_fault,
                            bool *writable, kvm_pfn_t *pfn)
{
        struct page *page[1];

        /*
         * Fast pin a writable pfn only if it is a write fault request
         * or the caller allows to map a writable pfn for a read fault
         * request.
         */
        if (!(write_fault || writable))
                return false;

        if (get_user_page_fast_only(addr, FOLL_WRITE, page)) {
                *pfn = page_to_pfn(page[0]);

                if (writable)
                        *writable = true;
                return true;
        }

        return false;
}
```


```cpp
static int hva_to_pfn_slow(unsigned long addr, bool *async, bool write_fault,
                           bool *writable, kvm_pfn_t *pfn)
{
        unsigned int flags = FOLL_HWPOISON;
        struct page *page;
        int npages = 0;

        might_sleep();

        if (writable)
                *writable = write_fault;

        if (write_fault)
                flags |= FOLL_WRITE;
        if (async)
                flags |= FOLL_NOWAIT;

        npages = get_user_pages_unlocked(addr, 1, &page, flags);
        if (npages != 1)
                return npages;

        /* map read fault as writable if possible */
        if (unlikely(!write_fault) && writable) {
                struct page *wpage;

                if (get_user_page_fast_only(addr, FOLL_WRITE, &wpage)) {
                        *writable = true;
                        put_page(page);
                        page = wpage;
                }
        }
        *pfn = page_to_pfn(page);
        return npages;
}
```

There are two variations of hva_to_pfn: hva_to_pfn_fast and hva_to_pfn_slow. The
fast version is invoked first and the slow version will be invoked only when the 
fast fails to translate hva to pfn, mostly due to absence of non-leaf page table
entries during the translation. The only noticeable difference is the assumption,
the fast version assumes that all non-leaf entries required for translations are 
already built, but the slow version does not. The slow version generates
non-leaf page table entries if they are not present. 

The core functionality of two functions, translating hva to pfn, is implemented
by the get_user_page_fast_only function. When the pfn associated with faulting 
GPA is found, page_to_pfn function will return the physical frame of the last 
level page frame. 

### Pinning GPA through get_user_pages 
>get_user_pages() is a way to map user-space memory into the kernel's address 
>space; it will ensure that all of the requested pages have been faulted into 
>RAM (and locked there) and provide a kernel mapping that, in turn, can be used
>for direct access by the kernel or (more often) to set up zero-copy I/O 
>operations. There are a number of variants of get_user_pages(), most notably 
>get_user_pages_fast(), which trades off some flexibility for the ability to 
>avoid acquiring the contended mmap_sem lock before doing its work. The ability
>to avoid copying data between kernel and user space makes get_user_pages() the 
>key to high-performance I/O. get_user_page_fast_only attempts to pin user page
>by walking the page tables without taking a lock. 

hva_to_pfn_\* functions actually invokes **get_user_page_fast_only** function 
to **pin the HVA. Remember that the HVA belongs to address space of guest 
process hosting KVM. The logistics of hva_to_pfn_ is like below:

>hva_to_pfn -> get_user_page_fast_only -> internal_get_user_pages_fast -> 
lockless_pages_from_mm -> gup_pgd_range

```cpp
static inline bool get_user_page_fast_only(unsigned long addr,
                        unsigned int gup_flags, struct page **pagep)
{
        return get_user_pages_fast_only(addr, 1, gup_flags, pagep) == 1;
}
```

```cpp
int get_user_pages_fast_only(unsigned long start, int nr_pages,
                             unsigned int gup_flags, struct page **pages)
{
        int nr_pinned;
        /*
         * Internally (within mm/gup.c), gup fast variants must set FOLL_GET,
         * because gup fast is always a "pin with a +1 page refcount" request.
         *
         * FOLL_FAST_ONLY is required in order to match the API description of
         * this routine: no fall back to regular ("slow") GUP.
         */
        gup_flags |= FOLL_GET | FOLL_FAST_ONLY;

        nr_pinned = internal_get_user_pages_fast(start, nr_pages, gup_flags,
                                                 pages);

        /*
         * As specified in the API description above, this routine is not
         * allowed to return negative values. However, the common core
         * routine internal_get_user_pages_fast() *can* return -errno.
         * Therefore, correct for that here:
         */
        if (nr_pinned < 0)
                nr_pinned = 0;

        return nr_pinned;
}
```

```cpp
static int internal_get_user_pages_fast(unsigned long start,
                                        unsigned long nr_pages,
                                        unsigned int gup_flags,
                                        struct page **pages)
{
        unsigned long len, end;
        unsigned long nr_pinned;
        int ret;

        if (WARN_ON_ONCE(gup_flags & ~(FOLL_WRITE | FOLL_LONGTERM |
                                       FOLL_FORCE | FOLL_PIN | FOLL_GET |
                                       FOLL_FAST_ONLY)))
                return -EINVAL;

        if (gup_flags & FOLL_PIN)
                mm_set_has_pinned_flag(&current->mm->flags);

        if (!(gup_flags & FOLL_FAST_ONLY))
                might_lock_read(&current->mm->mmap_lock);

        start = untagged_addr(start) & PAGE_MASK;
        len = nr_pages << PAGE_SHIFT;
        if (check_add_overflow(start, len, &end))
                return 0;
        if (unlikely(!access_ok((void __user *)start, len)))
                return -EFAULT;

        nr_pinned = lockless_pages_from_mm(start, end, gup_flags, pages);
        if (nr_pinned == nr_pages || gup_flags & FOLL_FAST_ONLY)
                return nr_pinned;

        /* Slow path: try to get the remaining pages with get_user_pages */
        start += nr_pinned << PAGE_SHIFT;
        pages += nr_pinned;
        ret = __gup_longterm_unlocked(start, nr_pages - nr_pinned, gup_flags,
                                      pages);
        if (ret < 0) {
                /*
                 * The caller has to unpin the pages we already pinned so
                 * returning -errno is not an option
                 */
                if (nr_pinned)
                        return nr_pinned;
                return ret;
        }
        return ret + nr_pinned;
}
```

```cpp
static unsigned long lockless_pages_from_mm(unsigned long start,
                                            unsigned long end,
                                            unsigned int gup_flags,
                                            struct page **pages)
{
        unsigned long flags;
        int nr_pinned = 0;
        unsigned seq;

        if (!IS_ENABLED(CONFIG_HAVE_FAST_GUP) ||
            !gup_fast_permitted(start, end))
                return 0;

        if (gup_flags & FOLL_PIN) {
                seq = raw_read_seqcount(&current->mm->write_protect_seq);
                if (seq & 1)
                        return 0;
        }

        local_irq_save(flags);
        gup_pgd_range(start, end, gup_flags, pages, &nr_pinned);
        local_irq_restore(flags);

        if (gup_flags & FOLL_PIN) {
                if (read_seqcount_retry(&current->mm->write_protect_seq, seq)) {
                        unpin_user_pages(pages, nr_pinned);
                        return 0;
                }
        }
        return nr_pinned;
}
```

### Software pagetable walking 
The **gup_pgd_range** does software based page table walking to locate PTE (host
physical address) mapped to the faulting GPA. If the PTE exists, it pins the PTE.
Note that it walks user process page table not the EPT. 
[[]]

>gup_pgd_range -> gup_p4d_range -> gup_pud_range -> gup_pmd_range ->
gup_pte_range

```cpp
static void gup_pgd_range(unsigned long addr, unsigned long end,
                unsigned int flags, struct page **pages, int *nr)
{
        unsigned long next;
        pgd_t *pgdp;

        pgdp = pgd_offset(current->mm, addr);
        do {
                pgd_t pgd = READ_ONCE(*pgdp);

                next = pgd_addr_end(addr, end);
                if (pgd_none(pgd))
                        return;
                if (unlikely(pgd_huge(pgd))) {
                        if (!gup_huge_pgd(pgd, pgdp, addr, next, flags,
                                          pages, nr))
                                return;
                } else if (unlikely(is_hugepd(__hugepd(pgd_val(pgd))))) {
                        if (!gup_huge_pd(__hugepd(pgd_val(pgd)), addr,
                                         PGDIR_SHIFT, next, flags, pages, nr))
                                return;
                } else if (!gup_p4d_range(pgdp, pgd, addr, next, flags, pages, nr))
                        return;
        } while (pgdp++, addr = next, addr != end);
}
```

```cpp
#define pgd_offset(mm, address)         pgd_offset_pgd((mm)->pgd, (address))

static inline pgd_t *pgd_offset_pgd(pgd_t *pgd, unsigned long address)
{
        return (pgd + pgd_index(address));
};

#define pgd_index(a)  (((a) >> PGDIR_SHIFT) & (PTRS_PER_PGD - 1))
#define PGDIR_SHIFT             39
#define PTRS_PER_PGD            512

#define PGDIR_SIZE      (_AC(1, UL) << PGDIR_SHIFT)
#define PGDIR_MASK      (~(PGDIR_SIZE - 1))

#define pgd_addr_end(addr, end)                                         \
({      unsigned long __boundary = ((addr) + PGDIR_SIZE) & PGDIR_MASK;  \
        (__boundary - 1 < (end) - 1)? __boundary: (end);                \
})
```


```cpp
static int gup_p4d_range(pgd_t *pgdp, pgd_t pgd, unsigned long addr, unsigned long end,
                         unsigned int flags, struct page **pages, int *nr)
{
        unsigned long next;
        p4d_t *p4dp;

        p4dp = p4d_offset_lockless(pgdp, pgd, addr);
        do {
                p4d_t p4d = READ_ONCE(*p4dp);

                next = p4d_addr_end(addr, end);
                if (p4d_none(p4d))
                        return 0;
                BUILD_BUG_ON(p4d_huge(p4d));
                if (unlikely(is_hugepd(__hugepd(p4d_val(p4d))))) {
                        if (!gup_huge_pd(__hugepd(p4d_val(p4d)), addr,
                                         P4D_SHIFT, next, flags, pages, nr))
                                return 0;
                } else if (!gup_pud_range(p4dp, p4d, addr, next, flags, pages, nr))
                        return 0;
        } while (p4dp++, addr = next, addr != end);

        return 1;
}
```

When p4d_none(p4d) returns true, then it returns 0 all the way up to 
hva_to_pfn_fast and fall through the hva_to_pfn_slow function. Remember that 
hva_to_pfn_fast function works only when the all associated page table entries 
present, which are required in translating faultin gpa -> hpa.

```cpp
static int gup_pte_range(pmd_t pmd, unsigned long addr, unsigned long end,
                         unsigned int flags, struct page **pages, int *nr)
{
        struct dev_pagemap *pgmap = NULL;
        int nr_start = *nr, ret = 0;
        pte_t *ptep, *ptem;

        ptem = ptep = pte_offset_map(&pmd, addr);
        do {
                pte_t pte = ptep_get_lockless(ptep);
                struct page *head, *page;

                /*
                 * Similar to the PMD case below, NUMA hinting must take slow
                 * path using the pte_protnone check.
                 */
                if (pte_protnone(pte))
                        goto pte_unmap;

                if (!pte_access_permitted(pte, flags & FOLL_WRITE))
                        goto pte_unmap;

                if (pte_devmap(pte)) {
                        if (unlikely(flags & FOLL_LONGTERM))
                                goto pte_unmap;

                        pgmap = get_dev_pagemap(pte_pfn(pte), pgmap);
                        if (unlikely(!pgmap)) {
                                undo_dev_pagemap(nr, nr_start, flags, pages);
                                goto pte_unmap;
                        }
                } else if (pte_special(pte))
                        goto pte_unmap;

                VM_BUG_ON(!pfn_valid(pte_pfn(pte)));
                page = pte_page(pte);

                head = try_grab_compound_head(page, 1, flags);
                if (!head)
                        goto pte_unmap;
                if (unlikely(page_is_secretmem(page))) {
                        put_compound_head(head, 1, flags);
                        goto pte_unmap;
                }

                if (unlikely(pte_val(pte) != pte_val(*ptep))) {
                        put_compound_head(head, 1, flags);
                        goto pte_unmap;
                }

                VM_BUG_ON_PAGE(compound_head(page) != head, page);

                /*
                 * We need to make the page accessible if and only if we are
                 * going to access its content (the FOLL_PIN case).  Please
                 * see Documentation/core-api/pin_user_pages.rst for
                 * details.
                 */
                if (flags & FOLL_PIN) {
                        ret = arch_make_page_accessible(page);
                        if (ret) {
                                unpin_user_page(page);
                                goto pte_unmap;
                        }
                }
                SetPageReferenced(page);
                pages[*nr] = page;
                (*nr)++;

        } while (ptep++, addr += PAGE_SIZE, addr != end);

        ret = 1;

pte_unmap:
        if (pgmap)
                put_dev_pagemap(pgmap);
        pte_unmap(ptem);
        return ret;
}
```
As a result of page table walking, all the pages mapped to faulting GPA will be
returned through pages parameter. 

```cpp
        if (get_user_page_fast_only(addr, FOLL_WRITE, page)) {                  
                *pfn = page_to_pfn(page[0]);                                    
                                                                                
                if (writable)                                                   
                        *writable = true;                                       
                return true;                                                    
        }             
```

Also the returned page is used to retrieve the HPA mapped to HVA and faulting 
GPA. 


# Resolve page fault (2nd part)
```cpp
4597 static int direct_page_fault(struct kvm_vcpu *vcpu, gpa_t gpa, u32 error_code,
4598                              bool prefault, int max_level, bool is_tdp,
4599                              kvm_pfn_t *pfn)
4600 {
......
4645         if (is_tdp_mmu_fault)
4646                 r = kvm_tdp_mmu_map(vcpu, gpa, error_code, map_writable, max_level,
4647                                     *pfn, prefault);
4648         else
4649                 r = __direct_map(vcpu, gpa, error_code, map_writable, max_level,
4650                                  *pfn, prefault, is_tdp);
```

After the kvm_faultin_pfn function is returned, the faulting GPA is translated 
into pfn as a result of software based host page table walking. The retrieved 
page frame entry, **pfn**, is passed to kvm_tdp_mmu_map or __direct_map based on
the platform configuration. 

## Setup SPT corresponding to the retrieved GPA->HPA mapping
If the TDP is enabled, kvm_tdp_mmu_map function is invoked to handle a TDP page 
fault (NPT/EPT violation/misconfiguration) by installing page tables and SPTEs 
to translate the faulting guest physical address. Note that previously it walked
**host process page table** not EPT. As a result of host process page table walk,
we retrieved the GVA->HVA->HPA mapping, so EPT page table entries should be 
properly installed to resolve VMEXIT caused by EPT violation. 

```cpp
 994 int kvm_tdp_mmu_map(struct kvm_vcpu *vcpu, gpa_t gpa, u32 error_code,
 995                     int map_writable, int max_level, kvm_pfn_t pfn,
 996                     bool prefault)
 997 {
 998         bool nx_huge_page_workaround_enabled = is_nx_huge_page_enabled();
 999         bool write = error_code & PFERR_WRITE_MASK;
1000         bool exec = error_code & PFERR_FETCH_MASK;
1001         bool huge_page_disallowed = exec && nx_huge_page_workaround_enabled;
1002         struct kvm_mmu *mmu = vcpu->arch.mmu;
1003         struct tdp_iter iter;
1004         struct kvm_mmu_page *sp;
1005         u64 *child_pt;
1006         u64 new_spte;
1007         int ret;
1008         gfn_t gfn = gpa >> PAGE_SHIFT;
1009         int level;
1010         int req_level;
1011 
1012         level = kvm_mmu_hugepage_adjust(vcpu, gfn, max_level, &pfn,
1013                                         huge_page_disallowed, &req_level);
1014 
1015         trace_kvm_mmu_spte_requested(gpa, level, pfn);
1016 
1017         rcu_read_lock();
1018 
1019         tdp_mmu_for_each_pte(iter, mmu, gfn, gfn + 1) {
......
1071         }
1072 
1073         if (iter.level != level) {
1074                 rcu_read_unlock();
1075                 return RET_PF_RETRY;
1076         }
1077 
1078         ret = tdp_mmu_map_handle_target_level(vcpu, write, map_writable, &iter,
1079                                               pfn, prefault);
1080         rcu_read_unlock();
1081 
1082         return ret;
1083 }
```

### Iterating SPTE to locate page frame mapping GFN -> HFN

Recall that we are working on to set up EPT entries associated with faultin 
GPA (gfn), so that MMU can smoothly walks the EPT page tables and translate 
VM's access on the faultin accessa to the HPA. To this end, we need to walk the 
EPT page tables to locate the entries associated with faultin GPA. Note that the
mmu->root_hpa holds the root address of the SPT, realized as EPT.

```cpp
#define tdp_mmu_for_each_pte(_iter, _mmu, _start, _end)         \
        for_each_tdp_pte(_iter, __va(_mmu->root_hpa),           \
                         _mmu->shadow_root_level, _start, _end)
        
#define for_each_tdp_pte(iter, root, root_level, start, end) \
        for_each_tdp_pte_min_level(iter, root, root_level, PG_LEVEL_4K, start, end)

/*
 * Iterates over every SPTE mapping the GFN range [start, end) in a
 * preorder traversal.
 */
#define for_each_tdp_pte_min_level(iter, root, root_level, min_level, start, end) \
        for (tdp_iter_start(&iter, root, root_level, min_level, start); \
             iter.valid && iter.gfn < end;                   \
             tdp_iter_next(&iter))
```

### Initialize the SPT iterator
```cpp
struct tdp_iter {
        /*
         * The iterator will traverse the paging structure towards the mapping
         * for this GFN.
         */
        gfn_t next_last_level_gfn;
        /*
         * The next_last_level_gfn at the time when the thread last
         * yielded. Only yielding when the next_last_level_gfn !=
         * yielded_gfn helps ensure forward progress.
         */
        gfn_t yielded_gfn;
        /* Pointers to the page tables traversed to reach the current SPTE */
        tdp_ptep_t pt_path[PT64_ROOT_MAX_LEVEL];
        /* A pointer to the current SPTE */
        tdp_ptep_t sptep;
        /* The lowest GFN mapped by the current SPTE */
        gfn_t gfn;
        /* The level of the root page given to the iterator */
        int root_level;
        /* The lowest level the iterator should traverse to */
        int min_level;
        /* The iterator's current level within the paging structure */
        int level;
        /* The address space ID, i.e. SMM vs. regular. */
        int as_id; 
        /* A snapshot of the value at sptep */
        u64 old_spte;
        /*
         * Whether the iterator has a valid state. This will be false if the
         * iterator walks off the end of the paging structure.
         */
        bool valid;
};
```


```cpp
/*
 * Sets a TDP iterator to walk a pre-order traversal of the paging structure
 * rooted at root_pt, starting with the walk to translate next_last_level_gfn.
 */
void tdp_iter_start(struct tdp_iter *iter, u64 *root_pt, int root_level,
                    int min_level, gfn_t next_last_level_gfn)
{
        WARN_ON(root_level < 1);
        WARN_ON(root_level > PT64_ROOT_MAX_LEVEL);

        iter->next_last_level_gfn = next_last_level_gfn;
        iter->root_level = root_level;
        iter->min_level = min_level;
        iter->pt_path[iter->root_level - 1] = (tdp_ptep_t)root_pt;
        iter->as_id = kvm_mmu_page_as_id(sptep_to_sp(root_pt));

        tdp_iter_restart(iter);
}
```

Note that **next_last_level_gfn is the faultin gfn**. And root_pt is the virtual 
address of **mmu->root_hpa which is the root address of the SPT**.

```cpp
void tdp_iter_restart(struct tdp_iter *iter)
{
        iter->yielded_gfn = iter->next_last_level_gfn;
        iter->level = iter->root_level; 

        iter->gfn = round_gfn_for_level(iter->next_last_level_gfn, iter->level);
        tdp_iter_refresh_sptep(iter);
        
        iter->valid = true;
}
```

tdp_iter_restart return the TDP iterator to the root PT and allow it to continue 
its traversal over the paging structure from there. Note that gfn field of the
iter returns the gfn masked with table index bits of current level. It also 
retrieves the next level page table entry (sptep) based on the gfn (from faultin
addr) and previous spte (from pt_path[cur_level-1]). Note that pt_path memorizes
spte of different level that were traversed while resolving the fault. Remember
that the next page table entry of the next level is calculated by adding the 
bits extracted from the faultin addr (as an index) and the root address of the 
page table of that level. 



```cpp
#define PAGE_SHIFT              12
#define PAGE_SIZE               (_AC(1,UL) << PAGE_SHIFT)
/* KVM Hugepage definitions for x86 */
#define KVM_MAX_HUGEPAGE_LEVEL  PG_LEVEL_1G
#define KVM_NR_PAGE_SIZES       (KVM_MAX_HUGEPAGE_LEVEL - PG_LEVEL_4K + 1)
#define KVM_HPAGE_GFN_SHIFT(x)  (((x) - 1) * 9)
#define KVM_HPAGE_SHIFT(x)      (PAGE_SHIFT + KVM_HPAGE_GFN_SHIFT(x))
#define KVM_HPAGE_SIZE(x)       (1UL << KVM_HPAGE_SHIFT(x))
#define KVM_HPAGE_MASK(x)       (~(KVM_HPAGE_SIZE(x) - 1))
#define KVM_PAGES_PER_HPAGE(x)  (KVM_HPAGE_SIZE(x) / PAGE_SIZE)

static gfn_t round_gfn_for_level(gfn_t gfn, int level)
{                       
        return gfn & -KVM_PAGES_PER_HPAGE(level);
}    
```

-KVM_PAGES_PER_HPAGE is equal to ~(KVM_PAGES_PER_HPAGE(level) - 1). Assuming 
that the root_level is 4 (shadow_root_level), the number will be 
>gfn & ~(KVM_PAGES_PER_HPAGE(4)-1)
>gfn & ~((KVM_HPAGE_SIZE(4) / 2^12) -1)
>gfn & ~(((1UL << KVM_HPAGE_SHIFT(4)) / 2^12) -1)  
>gfn & ~(((1UL << 39) / 2^12) -1)  
>gfn & ~(2^27 -1)

Note that the 2^39 is the start address of the PML4 in x86 architecture. Also
remember that the gfn is the page frame which is from faultin GPA >> PAGE_SHIFT.
That is the reason why 2^39 is divided by 2^12. Therefore gfn & ~(2^27-1) 
retrieves the all above bits starting from the start bits of the PML4. Under the
assumption of 48 bits of physical address, it extracts the bits located at 47 
(MSB) to 39(PML4).


```cpp
#define PT64_LEVEL_BITS 9

#define PT64_LEVEL_SHIFT(level) \ 
                (PAGE_SHIFT + (level - 1) * PT64_LEVEL_BITS)
        
#define PT64_INDEX(address, level)\
        (((address) >> PT64_LEVEL_SHIFT(level)) & ((1 << PT64_LEVEL_BITS) - 1))
#define SHADOW_PT_INDEX(addr, level) PT64_INDEX(addr, level)

/* Bits 9 and 10 are ignored by all non-EPT PTEs. */
#define DEFAULT_SPTE_HOST_WRITEABLE     BIT_ULL(9)
#define DEFAULT_SPTE_MMU_WRITEABLE      BIT_ULL(10)

static void tdp_iter_refresh_sptep(struct tdp_iter *iter)
{
        iter->sptep = iter->pt_path[iter->level - 1] +
                SHADOW_PT_INDEX(iter->gfn << PAGE_SHIFT, iter->level);
        iter->old_spte = READ_ONCE(*rcu_dereference(iter->sptep));
}
```

sptep field points to current SPTE address. Calculating its address is very 
similar to software based host page table walking, which selects specific bits 
from the GFN indicating the index of the SPT at that level. Also, the pth_path 
contains the root SPTE of different levels, so adding the two value retrieves
the next SPTE that iterator move on.

>iter->pt_path[iter->level - 1] + SHADOW_PT_INDEX(iter->gfn << PAGE_SHIFT, 
iter->level);
>root_hpa + SHADOW_PT_INDEX((iter->gfn) << 12, 4)
>root_hpa + ((iter->gfn << 12) >> 39) & ((1 << 9) - 1)
>root_hpa + (INDEX_OF_PML4) & (1 1111 1111)

This macro masks out the 9 bits from the gfn and retrieves actual index of PML4.
Note that each table index of different levels are generated with 9 bits of the 
faultin address, and this address location is determined based on the level. By
masking 9 LSB bits from the gfn left shifted with 12 and right shifted 39 again,
it can extract only the bits used for indexing PML4 table. Anyway the most 
important thing is sptep of the iter points to the SPTE derived from faultin
address and its PML4 index, which points to the next level SPT table, PDPT base
address in physical address. Also, old_spte is set with the same address.

## Walking SPT (Inside Iteration)
```cpp
1019         tdp_mmu_for_each_pte(iter, mmu, gfn, gfn + 1) {
1020                 if (nx_huge_page_workaround_enabled)
1021                         disallowed_hugepage_adjust(iter.old_spte, gfn,
1022                                                    iter.level, &pfn, &level);
1023 
1024                 if (iter.level == level)
1025                         break;
1026 
1027                 /*
1028                  * If there is an SPTE mapping a large page at a higher level
1029                  * than the target, that SPTE must be cleared and replaced
1030                  * with a non-leaf SPTE.
1031                  */
1032                 if (is_shadow_present_pte(iter.old_spte) &&
1033                     is_large_pte(iter.old_spte)) {
1034                         if (!tdp_mmu_zap_spte_atomic(vcpu->kvm, &iter))
1035                                 break;
1036 
1037                         /*
1038                          * The iter must explicitly re-read the spte here
1039                          * because the new value informs the !present
1040                          * path below.
1041                          */
1042                         iter.old_spte = READ_ONCE(*rcu_dereference(iter.sptep));
1043                 }
1044 
1045                 if (!is_shadow_present_pte(iter.old_spte)) {
1046                         /*
1047                          * If SPTE has been frozen by another thread, just
1048                          * give up and retry, avoiding unnecessary page table
1049                          * allocation and free.
1050                          */
1051                         if (is_removed_spte(iter.old_spte))
1052                                 break;
1053 
1054                         sp = alloc_tdp_mmu_page(vcpu, iter.gfn, iter.level - 1);
1055                         child_pt = sp->spt;
1056 
1057                         new_spte = make_nonleaf_spte(child_pt,
1058                                                      !shadow_accessed_mask);
1059 
1060                         if (tdp_mmu_set_spte_atomic_no_dirty_log(vcpu->kvm, &iter, new_spte)) {
1061                                 tdp_mmu_link_page(vcpu->kvm, sp,
1062                                                   huge_page_disallowed &&
1063                                                   req_level >= iter.level);
1064 
1065                                 trace_kvm_mmu_get_page(sp, true);
1066                         } else {
1067                                 tdp_mmu_free_sp(sp);
1068                                 break;
1069                         }
1070                 }
1071         }
1072 
1073         if (iter.level != level) {
1074                 rcu_read_unlock();
1075                 return RET_PF_RETRY;
1076         }
1077 
1078         ret = tdp_mmu_map_handle_target_level(vcpu, write, map_writable, &iter,
1079                                               pfn, prefault);
1080         rcu_read_unlock();
1081 
1082         return ret;
1083 }
```

### Initialize non-leaf SPTE (if not present)
During the traversing spt, it might encounter some cases where the spt entries 
are not yet allocated and cannot further go down to retrieve the HPA. 
```cpp
1045                 if (!is_shadow_present_pte(iter.old_spte)) {               
1046                         /*                                                 
1047                          * If SPTE has been frozen by another thread, just 
1048                          * give up and retry, avoiding unnecessary page table
1049                          * allocation and free.                            
1050                          */                                                
1051                         if (is_removed_spte(iter.old_spte))                
1052                                 break;                                     
1053                                                                            
1054                         sp = alloc_tdp_mmu_page(vcpu, iter.gfn, iter.level - 1);
```

```cpp
static inline bool is_shadow_present_pte(u64 pte)
{               
        return !!(pte & SPTE_MMU_PRESENT_MASK);
}    
```

To confirm whether the spte has been allocated or not, all initialized spte 
should be masked with SPTE_MMU_PRESENT_MASK bit. When the bit does not present
non-leaf spt table and its mapping should be established during the traversing. 

```cpp
static struct kvm_mmu_page *alloc_tdp_mmu_page(struct kvm_vcpu *vcpu, gfn_t gfn,
                                               int level)
{
        struct kvm_mmu_page *sp;

        sp = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_page_header_cache);
        sp->spt = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_shadow_page_cache);
        set_page_private(virt_to_page(sp->spt), (unsigned long)sp);

        sp->role.word = page_role_for_level(vcpu, level).word;
        sp->gfn = gfn;
        sp->tdp_mmu_page = true;

        trace_kvm_mmu_get_page(sp, true);

        return sp;
}
```

It allocates and return spt table page, kvm_mmu_page. Note that the gfn param 
is the gfn of the iter. 


```cpp
187 u64 make_nonleaf_spte(u64 *child_pt, bool ad_disabled)
188 {        
189         u64 spte = SPTE_MMU_PRESENT_MASK;      
190 
191         spte |= __pa(child_pt) | shadow_present_mask | PT_WRITABLE_MASK |
192                 shadow_user_mask | shadow_x_mask | shadow_me_mask;
193 
194         if (ad_disabled)
195                 spte |= SPTE_TDP_AD_DISABLED_MASK; 
196         else                      
197                 spte |= shadow_accessed_mask;
198 
199         return spte;
200 }        
```

```cpp
1054                         sp = alloc_tdp_mmu_page(vcpu, iter.gfn, iter.level - 1);
1055                         child_pt = sp->spt;                                
1056                                                                            
1057                         new_spte = make_nonleaf_spte(child_pt,             
1058                                                      !shadow_accessed_mask);
1060                         if (tdp_mmu_set_spte_atomic_no_dirty_log(vcpu->kvm, &iter, new_spte)) {
1061                                 tdp_mmu_link_page(vcpu->kvm, sp,
1062                                                   huge_page_disallowed &&
1063                                                   req_level >= iter.level);
```

Note that sp is the kvm_mmu_page for the child SPT, and child_pt points to the 
spt member field of the created sp. new_spte points to the physical address of 
the actual page table in the EPT with some flags enabled. Because lower 12 bits
are not used for page table entries of EPT, it can be used for carrying flags 
for that page table entry. 

To indicate that current spte is initialized, SPTE_MMU_PRESENT_MASK bit is set 
on spte address. Moreover, note that child_pt is the spt of the newly generated
SPT page. Remember that SPT page, kvm_mmu_page, is a kernel data structure to
maintain lots of information related with SPT including the actual page table 
entries. Therefore, from the hardware's perspective, this data structures should
not be seen, but only the spt maintained in the kvm_mmu_page should be seen so
that HW can walks the page table smoothly without considering those kernel 
defined data structure. After adding extra bits required to interpret spte, it 
returns new_spte further passed to the tdp_mmu_set_spte_atomic_no_dirty_log 
function to update SPTE for EPT.


```cpp
static inline bool tdp_mmu_set_spte_atomic_no_dirty_log(struct kvm *kvm,
                                                        struct tdp_iter *iter,
                                                        u64 new_spte)
{
        lockdep_assert_held_read(&kvm->mmu_lock);

        /*
         * Do not change removed SPTEs. Only the thread that froze the SPTE
         * may modify it.
         */
        if (is_removed_spte(iter->old_spte))
                return false;

        /*
         * Note, fast_pf_fix_direct_spte() can also modify TDP MMU SPTEs and
         * does not hold the mmu_lock.
         */
        if (cmpxchg64(rcu_dereference(iter->sptep), iter->old_spte,
                      new_spte) != iter->old_spte)
                return false;

        __handle_changed_spte(kvm, iter->as_id, iter->gfn, iter->old_spte,
                              new_spte, iter->level, true);
        handle_changed_spte_acc_track(iter->old_spte, new_spte, iter->level);

        return true;
}
```
Initially iter->sptep and iter->old_spte are set with identical address, 
cmpxchg64 will **exchange the value of iter->sptep to new_spte**. Now the 
current iter can point to the newly generated spte. Note that iter->sptep 
does not point to the kvm_mmu_page, but the spt field of the kvm_mmu_page. Now 
the SPT can go to lower level cause the new spte presents.

```cpp
 258 /**
 259  * tdp_mmu_link_page - Add a new page to the list of pages used by the TDP MMU
 260  *
 261  * @kvm: kvm instance
 262  * @sp: the new page
 263  * @account_nx: This page replaces a NX large page and should be marked for
 264  *              eventual reclaim.
 265  */
 266 static void tdp_mmu_link_page(struct kvm *kvm, struct kvm_mmu_page *sp,
 267                               bool account_nx)
 268 {
 269         spin_lock(&kvm->arch.tdp_mmu_pages_lock);
 270         list_add(&sp->link, &kvm->arch.tdp_mmu_pages);
 271         if (account_nx)
 272                 account_huge_nx_page(kvm, sp);
 273         spin_unlock(&kvm->arch.tdp_mmu_pages_lock);
 274 }
```

Up until now, the kvm_mmu_page is generated and its spt field is correctly 
mapped to the sptep field of the current iterator, which means that the EPT/NPT
can access next level SPTEs as a result of indexing with masking. However, the
newly generated kvm_mmu_page instance is also important because it maintains 
lots of useful information of that SPT page. Therefore, tdp_mmu_link_page links
the generated kvm_mmu_page to the list called kvm->arch.tdp_mmu_pages. 


### Advancing iterator to traverse SPT
We placed the new entry for SPT that has been absent. So now, we can further 
iterate the SPT!

```cpp
/*      
 * Step to the next SPTE in a pre-order traversal of the paging structure.
 * To get to the next SPTE, the iterator either steps down towards the goal
 * GFN, if at a present, non-last-level SPTE, or over to a SPTE mapping a
 * highter GFN.
 *      
 * The basic algorithm is as follows:
 * 1. If the current SPTE is a non-last-level SPTE, step down into the page
 *    table it points to.
 * 2. If the iterator cannot step down, it will try to step to the next SPTE
 *    in the current page of the paging structure.
 * 3. If the iterator cannot step to the next entry in the current page, it will
 *    try to step up to the parent paging structure page. In this case, that
 *    SPTE will have already been visited, and so the iterator must also step
 *    to the side again.
 */
void tdp_iter_next(struct tdp_iter *iter)
{
        if (try_step_down(iter))
                return;

        do {
                if (try_step_side(iter))
                        return;
        } while (try_step_up(iter));
        iter->valid = false; 
}
```
The basic operation of tdp_iter_next is the steps down one level according to 
the index masked from the next_last_level_gfn which is faultin gpa.

```cpp
/*
 * Steps down one level in the paging structure towards the goal GFN. Returns
 * true if the iterator was able to step down a level, false otherwise.
 */
static bool try_step_down(struct tdp_iter *iter)
{
        tdp_ptep_t child_pt;

        if (iter->level == iter->min_level)
                return false;

        /*
         * Reread the SPTE before stepping down to avoid traversing into page
         * tables that are no longer linked from this entry.
         */
        iter->old_spte = READ_ONCE(*rcu_dereference(iter->sptep));

        child_pt = spte_to_child_pt(iter->old_spte, iter->level);
        if (!child_pt)
                return false;

        iter->level--;
        iter->pt_path[iter->level - 1] = child_pt;
        iter->gfn = round_gfn_for_level(iter->next_last_level_gfn, iter->level);
        tdp_iter_refresh_sptep(iter);

        return true;
}
```

```cpp
tdp_ptep_t spte_to_child_pt(u64 spte, int level)        
{
        /*
         * There's no child entry if this entry isn't present or is a
         * last-level entry.
         */
        if (!is_shadow_present_pte(spte) || is_last_spte(spte, level))
                return NULL;

        return (tdp_ptep_t)__va(spte_to_pfn(spte) << PAGE_SHIFT);
}
```
>Given an SPTE and its level, returns a pointer containing the host virtual 
>address of the child page table referenced by the SPTE. Returns null if there 
>is no such entry.

Because the spte addresses are stored as physical addresses, it should be 
translated to virtual address first. Therefore, the child_pt is the next level
spt page's virtual address. Also, it decreases level as it steps down and 
memorize this address in the history path array, pt_path. As we did before, 
the next gfn is calculated based on level and faultin GPA. Also, function
tdp_iter_refresh_sptep initializes the sptep and old_spte based on new gfn.


## Final GPA -> HPA translation through leaf SPTE 
It will traverse the SPT one by one and end up reaching the last level SPTE,
PTE which is our final destination. Note that the last level would not be the 
PTE based on what page size will be used for faultin GPA. We assume that it is 
4K size PTE for simplification. Moreover, previous allocations for SPTE was for 
non-leaf entries, but PTE is the leaf entry. When it reaches the destination
level, it breaks the loop and invokes tdp_mmu_map_handle_target_level function.

```cpp
static int tdp_mmu_map_handle_target_level(struct kvm_vcpu *vcpu, int write,
                                          int map_writable,
                                          struct tdp_iter *iter,
                                          kvm_pfn_t pfn, bool prefault)
{
        u64 new_spte;
        int ret = RET_PF_FIXED;
        int make_spte_ret = 0;

        if (unlikely(is_noslot_pfn(pfn)))
                new_spte = make_mmio_spte(vcpu, iter->gfn, ACC_ALL);
        else
                make_spte_ret = make_spte(vcpu, ACC_ALL, iter->level, iter->gfn,
                                         pfn, iter->old_spte, prefault, true,
                                         map_writable, !shadow_accessed_mask,
                                         &new_spte);

        if (new_spte == iter->old_spte)
                ret = RET_PF_SPURIOUS;
        else if (!tdp_mmu_map_set_spte_atomic(vcpu, iter, new_spte))
                return RET_PF_RETRY;

        /*
         * If the page fault was caused by a write but the page is write
         * protected, emulation is needed. If the emulation was skipped,
         * the vCPU would have the same fault again.
         */
        if (make_spte_ret & SET_SPTE_WRITE_PROTECTED_PT) {
                if (write)
                        ret = RET_PF_EMULATE;
                kvm_make_request(KVM_REQ_TLB_FLUSH_CURRENT, vcpu);
        }

        /* If a MMIO SPTE is installed, the MMIO will need to be emulated. */
        if (unlikely(is_mmio_spte(vcpu->kvm, new_spte))) {
                trace_mark_mmio_spte(rcu_dereference(iter->sptep), iter->gfn,
                                     new_spte);
                ret = RET_PF_EMULATE;
        } else {
                trace_kvm_mmu_set_spte(iter->level, iter->gfn,
                                       rcu_dereference(iter->sptep));
        }

        /*
         * Increase pf_fixed in both RET_PF_EMULATE and RET_PF_FIXED to be
         * consistent with legacy MMU behavior.
         */
        if (ret != RET_PF_SPURIOUS)
                vcpu->stat.pf_fixed++;

        return ret;
}
```

tdp_mmu_map_handle_target_level function installs a last-level SPTE, which is 
the last journey of TDP page fault handling. Note that iter parameter contains 
all information describing which SPTE should be installed. It doesn't require 
GPA (gfn) because we already know address of SPTE entry that maps faultin GPA to
HPA. For correct translation, it also has HPA (pfn) param which will be written 
into the newly generated SPTE.

### Generate new spte for the last level entry
previously, for upper level non-leaf SPTEs, alloc_tdp_mmu_page and 
make_nonleaf_spte functions are used to allocate kvm_mmu_page and initialize 
spte, respectively. For the last level, we don't need kvm_mmu_page because it
is not a page table but the last entry mapping GPA to HPA. Therefore, make_spte
will be similar to make_nonleaf_spte function in terms of setting spte. 

```cpp
 93 int make_spte(struct kvm_vcpu *vcpu, unsigned int pte_access, int level,
 94                      gfn_t gfn, kvm_pfn_t pfn, u64 old_spte, bool speculative,
 95                      bool can_unsync, bool host_writable, bool ad_disabled,
 96                      u64 *new_spte)
 97 {           
 98         u64 spte = SPTE_MMU_PRESENT_MASK;
 99         int ret = 0;
100 
101         if (ad_disabled)
102                 spte |= SPTE_TDP_AD_DISABLED_MASK;
103         else if (kvm_vcpu_ad_need_write_protect(vcpu))
104                 spte |= SPTE_TDP_AD_WRPROT_ONLY_MASK;
105 
106         /*  
107          * For the EPT case, shadow_present_mask is 0 if hardware
108          * supports exec-only page table entries.  In that case,
109          * ACC_USER_MASK and shadow_user_mask are used to represent
110          * read access.  See FNAME(gpte_access) in paging_tmpl.h.
111          */
112         spte |= shadow_present_mask;
113         if (!speculative)
114                 spte |= spte_shadow_accessed_mask(spte);
115                     
116         if (level > PG_LEVEL_4K && (pte_access & ACC_EXEC_MASK) &&
117             is_nx_huge_page_enabled()) {
118                 pte_access &= ~ACC_EXEC_MASK;
119         }
120 
121         if (pte_access & ACC_EXEC_MASK)
122                 spte |= shadow_x_mask;
123         else
124                 spte |= shadow_nx_mask;
125             
126         if (pte_access & ACC_USER_MASK)
127                 spte |= shadow_user_mask;
128     
129         if (level > PG_LEVEL_4K)
130                 spte |= PT_PAGE_SIZE_MASK;
131         if (tdp_enabled)
132                 spte |= static_call(kvm_x86_get_mt_mask)(vcpu, gfn,
133                         kvm_is_mmio_pfn(pfn));
134 
135         if (host_writable)
136                 spte |= shadow_host_writable_mask;
137         else
138                 pte_access &= ~ACC_WRITE_MASK;
139 
140         if (!kvm_is_mmio_pfn(pfn))
141                 spte |= shadow_me_mask;
142 
143         spte |= (u64)pfn << PAGE_SHIFT;
144 
145         if (pte_access & ACC_WRITE_MASK) {
146                 spte |= PT_WRITABLE_MASK | shadow_mmu_writable_mask;
147 
148                 /*
149                  * Optimization: for pte sync, if spte was writable the hash
150                  * lookup is unnecessary (and expensive). Write protection
151                  * is responsibility of kvm_mmu_get_page / kvm_mmu_sync_roots.
152                  * Same reasoning can be applied to dirty page accounting.
153                  */
154                 if (!can_unsync && is_writable_pte(old_spte))
155                         goto out;
156 
157                 /*
158                  * Unsync shadow pages that are reachable by the new, writable
159                  * SPTE.  Write-protect the SPTE if the page can't be unsync'd,
160                  * e.g. it's write-tracked (upper-level SPs) or has one or more
161                  * shadow pages and unsync'ing pages is not allowed.
162                  */
163                 if (mmu_try_to_unsync_pages(vcpu, gfn, can_unsync)) {
164                         pgprintk("%s: found shadow page for %llx, marking ro\n",
165                                  __func__, gfn);
166                         ret |= SET_SPTE_WRITE_PROTECTED_PT;
167                         pte_access &= ~ACC_WRITE_MASK;
168                         spte &= ~(PT_WRITABLE_MASK | shadow_mmu_writable_mask);
169                 }
170         }
171 
172         if (pte_access & ACC_WRITE_MASK)
173                 spte |= spte_shadow_dirty_mask(spte);
174 
175         if (speculative)
176                 spte = mark_spte_for_access_track(spte);
177 
178 out:
179         WARN_ONCE(is_rsvd_spte(&vcpu->arch.mmu->shadow_zero_check, spte, level),
180                   "spte = 0x%llx, level = %d, rsvd bits = 0x%llx", spte, level,
181                   get_rsvd_bits(&vcpu->arch.mmu->shadow_zero_check, spte, level));
182 
183         *new_spte = spte;
184         return ret;
185 }
```

The most important role of make_spte function is setup spte flags according to 
platform setting and what level of spte it is. After setting up the flags, it 
combine the flags with pfn, so that the translation smoothly continues. However,
note that the initialized spte is stored at new_spte variable which does not
point to the last level STPE.


### Set generated SPTE to the leaf SPTE
```cpp
static inline bool tdp_mmu_map_set_spte_atomic(struct kvm_vcpu *vcpu,
                                               struct tdp_iter *iter,
                                               u64 new_spte)
{
        struct kvm *kvm = vcpu->kvm;

        if (!tdp_mmu_set_spte_atomic_no_dirty_log(kvm, iter, new_spte))
                return false;

        /*
         * Use kvm_vcpu_gfn_to_memslot() instead of going through
         * handle_changed_spte_dirty_log() to leverage vcpu->last_used_slot.
         */
        if (is_writable_pte(new_spte)) {
                struct kvm_memory_slot *slot = kvm_vcpu_gfn_to_memslot(vcpu, iter->gfn);

                if (slot && kvm_slot_dirty_track_enabled(slot)) {
                        /* Enforced by kvm_mmu_hugepage_adjust. */
                        WARN_ON_ONCE(iter->level > PG_LEVEL_4K);
                        mark_page_dirty_in_slot(kvm, slot, iter->gfn);
                }
        }

        return true;
}
```

Because SPTE can be shared among multiple VCPUs, the generated SPTE should be
atomically written into SPT. It invokes tdp_mmu_set_spte_atomic_no_dirty_log,
which is already covered in setting non-leaf spte. The vcpu param is the 
instance that took the TDP page fault. The iter param is a tdp_iter instance 
currently on the SPTE that should be set. The new_spte is the value the SPTE 
should be set to. After this function successfully returns, the page fault can 
be resolved, and the translation from faultin GPA to HPA will not fail again.

## MISC
### Some error codes related with page fault handling
```cpp
/*      
 * Return values of handle_mmio_page_fault, mmu.page_fault, and fast_page_fault().
 *      
 * RET_PF_RETRY: let CPU fault again on the address.
 * RET_PF_EMULATE: mmio page fault, emulate the instruction directly.
 * RET_PF_INVALID: the spte is invalid, let the real page fault path update it.
 * RET_PF_FIXED: The faulting entry has been fixed.
 * RET_PF_SPURIOUS: The faulting entry was already fixed, e.g. by another vCPU.
 *                                       
 * Any names added to this enum should be exported to userspace for use in
 * tracepoints via TRACE_DEFINE_ENUM() in mmutrace.h
 */             
enum {  
        RET_PF_RETRY = 0,
        RET_PF_EMULATE,
        RET_PF_INVALID,
        RET_PF_FIXED,
        RET_PF_SPURIOUS,
};
```
### Checking TDP
```cpp
static inline bool is_tdp_mmu_enabled(struct kvm *kvm) { return kvm->arch.tdp_mmu_enabled; }
static inline bool is_tdp_mmu_page(struct kvm_mmu_page *sp) { return sp->tdp_mmu_page; }
static inline bool is_tdp_mmu(struct kvm_mmu *mmu)
{
        struct kvm_mmu_page *sp;
        hpa_t hpa = mmu->root_hpa;
        
        if (WARN_ON(!VALID_PAGE(hpa)))
                return false;
        sp = to_shadow_page(hpa);
        return sp && is_tdp_mmu_page(sp) && sp->root_count;
}       
```

When TDP is enabled, **kvm_tdp_mmu_map** is invoked to handle EPT fault not 
through __direct_map function. root_hpa is a pointer to physical address of root
spt. If TDP is enabled, **root_hpa** has been initialized by the 
kvm_tdp_mmu_get_vcpu_root_hpa, tdp_mmu_page returns true. 



