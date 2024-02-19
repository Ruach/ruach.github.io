### Basic idea to implement private page 
>Because shared EPT is the same as the existing EPT, use the existing logic for
>shared EPT.  On the other hand, secure EPT requires additional operations
>instead of directly reading/writing of the EPT entry.
>
>On EPT violation, The KVM mmu walks down the EPT tree from the root, determines
>the EPT entry to operate, and updates the entry. If necessary, a TLB shootdown
>is done.  Because it's very slow to directly walk secure EPT by TDX SEAMCALL,
>TDH.MEM.SEPT.RD(), the mirror of secure EPT is created and maintained.  Add
>hooks to KVM MMU to reuse the existing code.

### Kernel log from VMExit to AUG
```cpp
[190678.041238]  __tdx_sept_set_private_spte.cold+0x6c/0x26e [kvm_intel]
[190678.041248]  ? do_huge_pmd_anonymous_page+0xf1/0x370
[190678.041251]  tdx_handle_changed_private_spte+0xee/0x270 [kvm_intel]
[190678.041259]  __handle_changed_spte+0x564/0x710 [kvm]
[190678.041297]  ? follow_pud_mask.isra.0+0x11e/0x1b0    
[190678.041299]  tdp_mmu_set_spte_atomic+0x117/0x190 [kvm]
[190678.041332]  tdp_mmu_map_handle_target_level+0x275/0x420 [kvm]
[190678.041363]  kvm_tdp_mmu_map+0x46b/0x7a0 [kvm]
[190678.041394]  ? get_user_pages_fast+0x24/0x50 
[190678.041397]  direct_page_fault+0x27a/0x340 [kvm]
[190678.041428]  kvm_tdp_page_fault+0x83/0xa0 [kvm]
[190678.041459]  ? x86_pmu_enable+0x1ab/0x490
[190678.041461]  kvm_mmu_page_fault+0x247/0x2c0 [kvm]
[190678.041491]  tdx_handle_ept_violation+0xe1/0x1a0 [kvm_intel]
[190678.041500]  __tdx_handle_exit+0x15e/0x220 [kvm_intel]
[190678.041507]  tdx_handle_exit+0x12/0x60 [kvm_intel]
[190678.041513]  vt_handle_exit+0x26/0x30 [kvm_intel]
[190678.041519]  vcpu_enter_guest+0x7ef/0x1000 [kvm]
```

### tdx_handle_ept_violation
When guest TD exits, it goes through below functions to handle TD exit events: 
vt_handle_exit -> __tdx_handle_exit. Based on the exit type of the TD, it jumps
to the different functions to handle the exit (refer to [[]]).

In this posting, we will follow the EXIT_REASON_EPT_VIOLATION exit reason, so it
jumps to tdx_handle_ept_violation.

```cpp
static int tdx_handle_ept_violation(struct kvm_vcpu *vcpu)
{
        union tdx_ext_exit_qualification ext_exit_qual;
        unsigned long exit_qual;
        int err_page_level = 0;

        ext_exit_qual.full = tdexit_ext_exit_qual(vcpu);

        if (ext_exit_qual.type >= NUM_EXT_EXIT_QUAL) {
                pr_err("EPT violation at gpa 0x%lx, with invalid ext exit qualification type 0x%x\n",
                        tdexit_gpa(vcpu), ext_exit_qual.type);
                kvm_vm_bugged(vcpu->kvm);
                return 0;
        } else if (ext_exit_qual.type == EXT_EXIT_QUAL_ACCEPT) {
                err_page_level = ext_exit_qual.req_sept_level + 1;
        }

        if (kvm_is_private_gpa(vcpu->kvm, tdexit_gpa(vcpu))) {
                /*
                 * Always treat SEPT violations as write faults.  Ignore the
                 * EXIT_QUALIFICATION reported by TDX-SEAM for SEPT violations.
                 * TD private pages are always RWX in the SEPT tables,
                 * i.e. they're always mapped writable.  Just as importantly,
                 * treating SEPT violations as write faults is necessary to
                 * avoid COW allocations, which will cause TDAUGPAGE failures
                 * due to aliasing a single HPA to multiple GPAs.
                 */
#define TDX_SEPT_VIOLATION_EXIT_QUAL    EPT_VIOLATION_ACC_WRITE
                exit_qual = TDX_SEPT_VIOLATION_EXIT_QUAL;
        } else {
                exit_qual = tdexit_exit_qual(vcpu);
                if (exit_qual & EPT_VIOLATION_ACC_INSTR) {
                        pr_warn("kvm: TDX instr fetch to shared GPA = 0x%lx @ RIP = 0x%lx\n",
                                tdexit_gpa(vcpu), kvm_rip_read(vcpu));
                        vcpu->run->exit_reason = KVM_EXIT_EXCEPTION;
                        vcpu->run->ex.exception = PF_VECTOR;
                        vcpu->run->ex.error_code = exit_qual;
                        return 0;
                }
        }

        trace_kvm_page_fault(tdexit_gpa(vcpu), exit_qual);
        return __vmx_handle_ept_violation(vcpu, tdexit_gpa(vcpu), exit_qual, err_page_level);
}
```

```cpp
static __always_inline unsigned long tdexit_gpa(struct kvm_vcpu *vcpu)
{
        return kvm_r8_read(vcpu);
}
```

```cpp
static inline bool kvm_is_private_gpa(const struct kvm *kvm, gpa_t gpa)
{               
        gfn_t mask = kvm_gfn_shared_mask(kvm);

        return mask && !(gpa_to_gfn(gpa) & mask);
}       
```

When TD exits because of the EPT violation, it passes the faultin GPA address 
through the r8 register to the VMM. Therefore, the tdx_handle_ept_violation 
function checks if the faultin address is private. If it is not a private, then 
TD exit happens while it tries to fetch instructions from non-private memory, 
which doesn't need further handling operations. If it is private, then it should 
be handled by the VMM layer to resolve fault.


```cpp
static __always_inline unsigned long tdexit_ext_exit_qual(struct kvm_vcpu *vcpu)
{
        return kvm_rdx_read(vcpu);
}

```

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
        error_code |= (exit_qualification & EPT_VIOLATION_RWX_MASK)
                      ? PFERR_PRESENT_MASK : 0;

        error_code |= (exit_qualification & EPT_VIOLATION_GVA_TRANSLATED) != 0 ?
               PFERR_GUEST_FINAL_MASK : PFERR_GUEST_PAGE_MASK;

        if (err_page_level > PG_LEVEL_NONE)
                error_code |= (err_page_level << PFERR_LEVEL_START_BIT) & PFERR_LEVEL_MASK;

        return kvm_mmu_page_fault(vcpu, gpa, error_code, NULL, 0);
}
```
If the faultin GPA belongs to the private memory, VMM can retrieves the exit
qualification through the rdx register. Above function parses the qualification 
and passes the error_code to the kvm_mmu_page_fault function. Note that TDX 
private page fault is treated as write fault (\XXX is it true?).

### Handling page fault 
Now we have most of the information about the fault. Let's handle page fault!
```cpp
int noinline kvm_mmu_page_fault(struct kvm_vcpu *vcpu, gpa_t cr2_or_gpa, u64 error_code,
                       void *insn, int insn_len)
{
        int r, emulation_type = EMULTYPE_PF;
        bool direct = vcpu->arch.mmu->root_role.direct;

        if (WARN_ON(!VALID_PAGE(vcpu->arch.mmu->root.hpa)))
                return RET_PF_RETRY;

        r = RET_PF_INVALID;
        if (unlikely(error_code & PFERR_RSVD_MASK)) {
                r = handle_mmio_page_fault(vcpu, cr2_or_gpa, direct);
                if (r == RET_PF_EMULATE)
                        goto emulate;
        }

        if (r == RET_PF_INVALID) {
                r = kvm_mmu_do_page_fault(vcpu, cr2_or_gpa,
                                          lower_32_bits(error_code), false);
                if (KVM_BUG_ON(r == RET_PF_INVALID, vcpu->kvm))
                        return -EIO;
        }

        if (r == RET_PF_USER)
                return 0;

        if (r < 0)
                return r;
        if (r != RET_PF_EMULATE)
                return 1;

        /*
         * Before emulating the instruction, check if the error code
         * was due to a RO violation while translating the guest page.
         * This can occur when using nested virtualization with nested
         * paging in both guests. If true, we simply unprotect the page
	 * and resume the guest.
         */
        if (vcpu->arch.mmu->root_role.direct &&
            (error_code & PFERR_NESTED_GUEST_PAGE) == PFERR_NESTED_GUEST_PAGE) {
                kvm_mmu_unprotect_page(vcpu->kvm, gpa_to_gfn(cr2_or_gpa));
                return 1;
        }

        /*
         * vcpu->arch.mmu.page_fault returned RET_PF_EMULATE, but we can still
         * optimistically try to just unprotect the page and let the processor
         * re-execute the instruction that caused the page fault.  Do not allow
         * retrying MMIO emulation, as it's not only pointless but could also
         * cause us to enter an infinite loop because the processor will keep
         * faulting on the non-existent MMIO address.  Retrying an instruction
         * from a nested guest is also pointless and dangerous as we are only
         * explicitly shadowing L1's page tables, i.e. unprotecting something
         * for L1 isn't going to magically fix whatever issue cause L2 to fail.
         */
        if (!mmio_info_in_cache(vcpu, cr2_or_gpa, direct) && !is_guest_mode(vcpu))
                emulation_type |= EMULTYPE_ALLOW_RETRY_PF;
emulate:
        return x86_emulate_instruction(vcpu, cr2_or_gpa, emulation_type, insn,
                                       insn_len);
}
```


```cpp
static inline int kvm_mmu_do_page_fault(struct kvm_vcpu *vcpu, gpa_t cr2_or_gpa,
                                        u32 err, bool prefetch)
{                       
        struct kvm_page_fault fault = {
                .addr = cr2_or_gpa,
                .error_code = err,
                .exec = err & PFERR_FETCH_MASK, 
                .write = err & PFERR_WRITE_MASK,
                .present = err & PFERR_PRESENT_MASK,
                .rsvd = err & PFERR_RSVD_MASK,
                .user = err & PFERR_USER_MASK,
                .prefetch = prefetch,
                .is_tdp = likely(vcpu->arch.mmu->page_fault == kvm_tdp_page_fault),
                .nx_huge_page_workaround_enabled = is_nx_huge_page_enabled(),
                .is_private = kvm_is_private_gpa(vcpu->kvm, cr2_or_gpa),
        
                .max_level = vcpu->kvm->arch.tdp_max_page_level,
                .req_level = PG_LEVEL_4K,
                .goal_level = PG_LEVEL_4K,
        };
        int r;

        /*
         * Async #PF "faults", a.k.a. prefetch faults, are not faults from the
         * guest perspective and have already been counted at the time of the
         * original fault.
         */
        if (!prefetch)
                vcpu->stat.pf_taken++;

        if (IS_ENABLED(CONFIG_RETPOLINE) && fault.is_tdp)
                r = kvm_tdp_page_fault(vcpu, &fault);
        else
                r = vcpu->arch.mmu->page_fault(vcpu, &fault);
        /*
         * Similar to above, prefetch faults aren't truly spurious, and the
         * async #PF path doesn't do emulation.  Do count faults that are fixed
         * by the async #PF handler though, otherwise they'll never be counted.
         */
        if (r == RET_PF_FIXED)
                vcpu->stat.pf_fixed++;
        else if (prefetch)
                ;
        else if (r == RET_PF_EMULATE)
                vcpu->stat.pf_emulate++;
        else if (r == RET_PF_SPURIOUS)
                vcpu->stat.pf_spurious++;
        return r;
}
```

It injects the fault to the page fault handler. It is highly likely that the 
TDX utilize the tdp, so it will invoke kvm_tdp_page_fault function.

### Fault handling (for TDX)
>The **kvm_faultin_pfn** function resolves GPA -> HVA mapping and pin the HVA.
To translate GPA to HVA, the memslot instance associated with the faultin GPA
is required. 


```cpp
static int kvm_faultin_pfn(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault)
{
        struct kvm_memory_slot *slot = fault->slot;
        bool async;
        int r;

        /*
         * Retry the page fault if the gfn hit a memslot that is being deleted
         * or moved.  This ensures any existing SPTEs for the old memslot will
         * be zapped before KVM inserts a new MMIO SPTE for the gfn.
         */
        if (slot && (slot->flags & KVM_MEMSLOT_INVALID))
                return RET_PF_RETRY;

        if (!kvm_is_visible_memslot(slot)) {
                /* Don't expose private memslots to L2. */
                if (is_guest_mode(vcpu)) {
                        fault->slot = NULL;
                        fault->pfn = KVM_PFN_NOSLOT;
                        fault->map_writable = false;
                        return RET_PF_CONTINUE;
                }
                /*
                 * If the APIC access page exists but is disabled, go directly
                 * to emulation without caching the MMIO access or creating a
                 * MMIO SPTE.  That way the cache doesn't need to be purged
                 * when the AVIC is re-enabled.
                 */
                if (slot && slot->id == APIC_ACCESS_PAGE_PRIVATE_MEMSLOT &&
                    !kvm_apicv_activated(vcpu->kvm))
                        return RET_PF_EMULATE;
        }

        if (kvm_slot_is_private(slot)) {
                r = kvm_faultin_pfn_private(vcpu, fault);
                if (r != RET_PF_CONTINUE)
                        return r == RET_PF_FIXED ? RET_PF_CONTINUE : r;
        } else if (fault->is_private)
                return kvm_faultin_pfn_private_mapped(vcpu, fault);
        async = false;
        fault->pfn = __gfn_to_pfn_memslot(slot, fault->gfn, false, &async,
                                          fault->write, &fault->map_writable,
                                          &fault->hva);
```
When the faultin address does not belong to private memory space for TD, then 
__gfn_to_pfn_memslot function translate gfn to pfn. Otherwise (TDX private), 
it invokes kvm_faultin_pfn_private function when private_file has been assigned 
or kvm_faultin_pfn_private_mapped without private_fd (most of the cases). 

```cpp
/*
 * Private page can't be release on mmu_notifier without losing page contents.
 * The help, callback, from backing store is needed to allow page migration.
 * For now, pin the page.
 */
static int kvm_faultin_pfn_private_mapped(struct kvm_vcpu *vcpu,
                                           struct kvm_page_fault *fault)
{
        hva_t hva = gfn_to_hva_memslot(fault->slot, fault->gfn);
        struct page *page[1];

        fault->map_writable = false;
        fault->pfn = KVM_PFN_ERR_FAULT;
        if (hva == KVM_HVA_ERR_RO_BAD || hva == KVM_HVA_ERR_BAD)
                return RET_PF_INVALID;

        /* TDX allows only RWX.  Read-only isn't supported. */
        WARN_ON_ONCE(!fault->write);
        if (get_user_pages_fast(hva, 1, FOLL_WRITE, page) != 1)
                return RET_PF_INVALID;

        fault->map_writable = true;
        fault->pfn = page_to_pfn(page[0]);
        return RET_PF_CONTINUE;
}
```

It invokes get_user_pages_fast function to walk page table to find HPA mapping
for hva and pin it. Also it assigns the pfn to the injected fault so that it can
be handled later to generate mapping in the private EPT (GPA -> HPA).


### Handling the fault (setting EPT)
```cpp
/*
 * Handle a TDP page fault (NPT/EPT violation/misconfiguration) by installing
 * page tables and SPTEs to translate the faulting guest physical address.
 */
int kvm_tdp_mmu_map(struct kvm_vcpu *vcpu, struct kvm_page_fault *fault)
{
        struct kvm_mmu *mmu = vcpu->arch.mmu;
        struct tdp_iter iter;
        gfn_t raw_gfn;
        bool is_private = fault->is_private;
        int ret;

        kvm_mmu_hugepage_adjust(vcpu, fault);

        trace_kvm_mmu_spte_requested(fault);

        rcu_read_lock();

        raw_gfn = gpa_to_gfn(fault->addr);

        if (is_error_noslot_pfn(fault->pfn) || kvm_is_reserved_pfn(fault->pfn)) {
                if (is_private) {
                        rcu_read_unlock();
                        return -EFAULT;
                }
        }

        tdp_mmu_for_each_pte(iter, mmu, is_private, raw_gfn, raw_gfn + 1) {
                WARN_ON(iter.is_private != is_private);
                WARN_ON(is_private_sptep(iter.sptep) != is_private);

                /*
                 * In private GPA case, cannot map a private page to higher
                 * level if smaller level mapping exists.  It can be promoted to
                 * larger mapping later when all the smaller mapping are there.
                 */
                if (fault->nx_huge_page_workaround_enabled || is_private)
                        disallowed_hugepage_adjust(fault, iter.old_spte, iter.level);

                if (iter.level == fault->goal_level)
                        break;

                /*
                 * Check zapped large page firstly, this allows us continue to
                 * split the large private page after unzap the pte back.
                 */
                if (is_private_zapped_spte(iter.old_spte) &&
                    is_large_pte(iter.old_spte)) {
                        if (tdp_mmu_unzap_large_spte(vcpu, fault, &iter) !=
                            RET_PF_CONTINUE)
                                break;
                        iter.old_spte = kvm_tdp_mmu_read_spte(iter.sptep);
                }

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

                if (!is_shadow_present_pte(iter.old_spte)) {
                        bool account_nx = fault->huge_page_disallowed &&
                                fault->req_level >= iter.level;

                        /*
                         * If SPTE has been frozen by another thread, just
                         * give up and retry, avoiding unnecessary page table
                         * allocation and free.
                         */
                        if (is_removed_spte(iter.old_spte))
                                break;

                        if (tdp_mmu_populate_nonleaf(vcpu, &iter, account_nx))
                                break;
                }
        }

        /*
         * Force the guest to retry the access if the upper level SPTEs aren't
         * in place, or if the target leaf SPTE is frozen by another CPU.
         */
        if (iter.level != fault->goal_level || is_removed_spte(iter.old_spte)) {
                rcu_read_unlock();
                return RET_PF_RETRY;
        }

        ret = tdp_mmu_map_handle_target_level(vcpu, fault, &iter);
        rcu_read_unlock();

        return ret;
}
```

```cpp
#define tdp_mmu_for_each_pte(_iter, _mmu, _private, _start, _end)       \
        for_each_tdp_pte(_iter,                                         \
                 to_shadow_page((_private) ? _mmu->private_root_hpa :   \
                                _mmu->root.hpa),                        \
                _start, _end)
```







### Set new SPTE entry
When a guest VM makes a memory access, the TDP MMU checks the guest's page 
tables and translates the virtual address to a physical address. If the guest's
page tables are not present in the TDP MMU's cache, the hypervisor intercepts 
the page fault and updates the **TDP MMU cache** with the appropriate guest page
table entries. **tdp_mmu_set_spte_atomic** is used to set the PTE for a specific
guest virtual address in the TDP MMU. It is called when the hypervisor needs to 
modify a guest PTE, such as when adding or removing a mapping from a guest's 
virtual address space. Because we are handling the page fault, it needs to map 
new entry in the SPT, and the atomic function properly inserts new entry to the
SPT. Note that make_spte function in the tdp_mmu_map_handle_target_level 
generates the new spte entry to be inserted. For the details please refer to 
[[]]. Also note that tdp_mmu_set_spte_atomic is called instaed of the 
tdp_mmu_map_set_spte_atomic. 


```cpp
/*
 * tdp_mmu_set_spte_atomic - Set a TDP MMU SPTE atomically
 * and handle the associated bookkeeping.  Do not mark the page dirty
 * in KVM's dirty bitmaps.
 *
 * If setting the SPTE fails because it has changed, iter->old_spte will be
 * refreshed to the current value of the spte.
 *
 * @kvm: kvm instance
 * @iter: a tdp_iter instance currently on the SPTE that should be set
 * @new_spte: The value the SPTE should be set to
 * Return:
 * * 0      - If the SPTE was set.
 * * -EBUSY - If the SPTE cannot be set. In this case this function will have
 *            no side-effects other than setting iter->old_spte to the last
 *            known value of the spte.
 */
static inline int tdp_mmu_set_spte_atomic(struct kvm *kvm,
                                          struct tdp_iter *iter,
                                          u64 new_spte)
{
        bool freeze_spte = iter->is_private && !is_removed_spte(new_spte);
        u64 tmp_spte = freeze_spte ? REMOVED_SPTE : new_spte;
        u64 *sptep = rcu_dereference(iter->sptep);
        u64 old_spte;

        WARN_ON_ONCE(iter->yielded);
        WARN_ON(is_private_sptep(iter->sptep) != iter->is_private);

        /*
         * The caller is responsible for ensuring the old SPTE is not a REMOVED
         * SPTE.  KVM should never attempt to zap or manipulate a REMOVED SPTE,
         * and pre-checking before inserting a new SPTE is advantageous as it
         * avoids unnecessary work.
         */
        WARN_ON_ONCE(iter->yielded || is_removed_spte(iter->old_spte));

        lockdep_assert_held_read(&kvm->mmu_lock);

        /*
         * Note, fast_pf_fix_direct_spte() can also modify TDP MMU SPTEs and
         * does not hold the mmu_lock.
         */
        old_spte = cmpxchg64(sptep, iter->old_spte, tmp_spte);
        if (old_spte != iter->old_spte) {
                /*
                 * The page table entry was modified by a different logical
                 * CPU. Refresh iter->old_spte with the current value so the
                 * caller operates on fresh data, e.g. if it retries
                 * tdp_mmu_set_spte_atomic().
                 */
                iter->old_spte = old_spte;
                return -EBUSY;
        }

        __handle_changed_spte(
                kvm, iter->as_id, iter->gfn, iter->is_private,
                iter->old_spte, new_spte, iter->level, true);
        handle_changed_spte_acc_track(iter->old_spte, new_spte, iter->level);

        if (freeze_spte)
                __kvm_tdp_mmu_write_spte(sptep, new_spte);

        return 0;
}
```

The function takes an argument for the new PTE value and performs an atomic swap
operation to set the new PTE in the TDP MMU cache. The function also performs 
various checks and updates to ensure that the new PTE is valid and that the TDP 
MMU cache is consistent with the guest's page tables. 


## Handling (architecture specific) page table changes 
The purpose of __handle_changed_spte is to update the virtual memory mappings in
response to changes in the SPTE. For example, if the SPTE's permissions were 
changed to disallow write access, the function may need to update the 
corresponding page table entry to indicate that the page is read-only. The 
function may also need to perform other operations, such as updating the dirty 
bit, clearing the accessed bit, or invalidating TLB entries. Just updating the 
SPTE doesn't change the page table related hardware registers automatically. 

```cpp
/**
 * __handle_changed_spte - handle bookkeeping associated with an SPTE change
 * @kvm: kvm instance
 * @as_id: the address space of the paging structure the SPTE was a part of
 * @gfn: the base GFN that was mapped by the SPTE
 * @private_spte: the SPTE is private or not
 * @old_spte: The value of the SPTE before the change
 * @new_spte: The value of the SPTE after the change
 * @level: the level of the PT the SPTE is part of in the paging structure
 * @shared: This operation may not be running under the exclusive use of
 *          the MMU lock and the operation must synchronize with other
 *          threads that might be modifying SPTEs.
 *
 * Handle bookkeeping that might result from the modification of a SPTE.
 * This function must be called for all TDP SPTE modifications.
 */
static void __handle_changed_spte(struct kvm *kvm, int as_id, gfn_t gfn,
                                  bool private_spte, u64 old_spte,
                                  u64 new_spte, int level, bool shared)
{
        bool was_present = is_shadow_present_pte(old_spte);
        bool is_present = is_shadow_present_pte(new_spte);
        bool was_last = is_last_spte(old_spte, level);
        bool is_last = is_last_spte(new_spte, level);
        bool was_leaf = was_present && was_last;
        bool is_leaf = is_present && is_last;
        kvm_pfn_t old_pfn = spte_to_pfn(old_spte);
        kvm_pfn_t new_pfn = spte_to_pfn(new_spte);
        bool pfn_changed = old_pfn != new_pfn;
        bool was_private_zapped = is_private_zapped_spte(old_spte);
        bool is_private_zapped = is_private_zapped_spte(new_spte);
        struct kvm_spte_change change = {
                .gfn = gfn,
                .level = level,
		.old = {
                        .pfn = old_pfn,
                        .is_present = was_present,
                        .is_last = was_last,
                        .is_private_zapped = was_private_zapped,
                },
                .new = {
                        .pfn = new_pfn,
                        .is_present = is_present,
                        .is_last = is_last,
                        .is_private_zapped = is_private_zapped,
                },
        };

        WARN_ON(level > PT64_ROOT_MAX_LEVEL);
        WARN_ON(level < PG_LEVEL_4K);
        WARN_ON(gfn & (KVM_PAGES_PER_HPAGE(level) - 1));
        WARN_ON(kvm_is_private_gpa(kvm, gfn_to_gpa(gfn)) != private_spte);
        WARN_ON(was_private_zapped && !private_spte);

        /*
         * If this warning were to trigger it would indicate that there was a
         * missing MMU notifier or a race with some notifier handler.
         * A present, leaf SPTE should never be directly replaced with another
         * present leaf SPTE pointing to a different PFN. A notifier handler
         * should be zapping the SPTE before the main MM's page table is
         * changed, or the SPTE should be zeroed, and the TLBs flushed by the
         * thread before replacement.
         */
        if (was_leaf && is_leaf && pfn_changed) {
                pr_err("Invalid SPTE change: cannot replace a present leaf\n"
                       "SPTE with another present leaf SPTE mapping a\n"
                       "different PFN!\n"
                       "as_id: %d gfn: %llx old_spte: %llx new_spte: %llx level: %d",
                       as_id, gfn, old_spte, new_spte, level);

                /*
                 * Crash the host to prevent error propagation and guest data
                 * corruption.
                 */
                BUG();
        }

        if (old_spte == new_spte)
                return;

        trace_kvm_tdp_mmu_spte_changed(as_id, gfn, level, old_spte, new_spte);

        if (is_leaf)
                check_spte_writable_invariants(new_spte);

        if (was_private_zapped) {
                change.sept_page = tdx_get_sept_page(&change);
                WARN_ON(is_private_zapped);
                static_call(kvm_x86_handle_private_zapped_spte)(kvm, &change);
                /* Temporarily blocked private SPTE can only be leaf. */
                WARN_ON(!is_last_spte(old_spte, level));
                return;
        }

        /*
         * The only times a SPTE should be changed from a non-present to
         * non-present state is when an MMIO entry is installed/modified/
         * removed. In that case, there is nothing to do here.
         */
        if (!was_present && !is_present) {
                /*
                 * If this change does not involve a MMIO SPTE or removed SPTE,
                 * it is unexpected. Log the change, though it should not
                 * impact the guest since both the former and current SPTEs
                 * are nonpresent.
                 */
                if (WARN_ON(!is_mmio_spte(kvm, old_spte) &&
                            !is_mmio_spte(kvm, new_spte) &&
                            !is_removed_spte(new_spte)))
                        pr_err("Unexpected SPTE change! Nonpresent SPTEs\n"
                               "should not be replaced with another,\n"
                               "different nonpresent SPTE, unless one or both\n"
                               "are MMIO SPTEs, or the new SPTE is\n"
                               "a temporary removed SPTE.\n"
                               "as_id: %d gfn: %llx old_spte: %llx new_spte: %llx level: %d",
                               as_id, gfn, old_spte, new_spte, level);
                return;
        }

        if (is_leaf != was_leaf)
                kvm_update_page_stats(kvm, level, is_leaf ? 1 : -1);

        if (was_leaf && is_dirty_spte(old_spte) &&
            (!is_present || !is_dirty_spte(new_spte) || pfn_changed))
                kvm_set_pfn_dirty(old_pfn);

        /*
         * Recursively handle child PTs if the change removed a subtree from
         * the paging structure.  Note the WARN on the PFN changing without the
         * SPTE being converted to a hugepage (leaf) or being zapped.  Shadow
         * pages are kernel allocations and should never be migrated.
         */
        if (was_present && !was_last &&
            (is_leaf || !is_present || WARN_ON_ONCE(pfn_changed))) {
                WARN_ON(private_spte !=
                        is_private_sptep(spte_to_child_pt(old_spte, level)));
                handle_removed_pt(kvm, spte_to_child_pt(old_spte, level),
                                  private_spte, shared);
        }

        /*
         * Special handling for the private mapping.  We are either
         * setting up new mapping at middle level page table, or leaf,
         * or tearing down existing mapping.
         *
         * This is after handling lower page table by above
         * handle_remove_tdp_mmu_page().  S-EPT requires to remove S-EPT tables
         * after removing childrens.
         */
        if (private_spte &&
            /* Ignore change of software only bits. e.g. host_writable */
            (was_leaf != is_leaf || was_present != is_present || pfn_changed ||
             was_private_zapped != is_private_zapped)) {
                change.sept_page = tdx_get_sept_page(&change);
                WARN_ON(was_private_zapped && is_private_zapped);
                /*
                 * When write lock is held, leaf pte should be zapping or
                 * prohibiting.  Not directly was_present=1 -> zero EPT entry.
                 */
                WARN_ON(!shared && is_leaf &&
                        !is_private_zapped);
                static_call(kvm_x86_handle_changed_private_spte)(kvm, &change);
        }
}
```

>Allocate protected page table for private page table, and add hooks to
>operate on protected page table.  This patch adds allocation/free of
>protected page tables and hooks.  When calling hooks to update SPTE entry,
>freeze the entry, call hooks and unfreeze the entry to allow concurrent
>updates on page tables.  Which is the advantage of TDP MMU.  As
>kvm_gfn_shared_mask() returns false always, those hooks aren't called yet
>with this patch.
>
>When the faulting GPA is private, the KVM fault is called private.  When
>resolving private KVM fault, allocate protected page table and call hooks
>to operate on protected page table. On the change of the private PTE entry,
>invoke kvm_x86_ops hook in __handle_changed_spte() to propagate the change
>to protected page table. The following depicts the relationship.
>
>For protected page table, hooks are called to update protected page table
>in addition to direct access to the private SPTE. For the zapping case, it
>works to freeze the SPTE. It can call hooks in addition to TLB shootdown.
>For populating the private SPTE entry, there can be a race condition
>without further protection
>
>  vcpu 1: populating 2M private SPTE
>  vcpu 2: populating 4K private SPTE
>  vcpu 2: TDX SEAMCALL to update 4K protected SPTE => error
>  vcpu 1: TDX SEAMCALL to update 2M protected SPTE
>
>To avoid the race, the frozen SPTE is utilized.  Instead of atomic update
>of the private entry, freeze the entry, call the hook that update protected
>SPTE, set the entry to the final value.
>
>Support 4K page only at this stage.  2M page support can be done in future
>patches.


## Hooks for TDX private page update (__handle_changed_spte) 

### kvm_x86_handle_private_zapped_spte
>The existing KVM TDP MMU code uses atomic update of SPTE.  On populating
>the EPT entry, atomically set the entry.  However, it requires TLB
>shootdown to zap SPTE.  To address it, the entry is frozen with the special
>SPTE value that clears the present bit. After the TLB shootdown, the entry
>is set to the eventual value (unfreeze).

```cpp
        if (was_private_zapped) {
                change.sept_page = tdx_get_sept_page(&change);
                WARN_ON(is_private_zapped);
                static_call(kvm_x86_handle_private_zapped_spte)(kvm, &change);
                /* Temporarily blocked private SPTE can only be leaf. */
                WARN_ON(!is_last_spte(old_spte, level));
                return;
        }
```
For shadow page (sp) covering private memories, each spte (kvm_mmu_page) has
private_sp memory field to point to page address used as S-EPT page by the TDX
module. Note that the spte is mirror of the S-EPT in the KVM module side. To 
let TDX module know which S-EPT page should be modified based on VMM decisions, 
it should passes the S-EPT page address to proper SEAMCALL. 


```cpp
static void *tdx_get_sept_page(const struct kvm_spte_change *change)
{
        if (change->new.is_present && !change->new.is_last) {
                struct kvm_mmu_page *sp = to_shadow_page(pfn_to_hpa(change->new.pfn));
                void *sept_page = kvm_mmu_private_sp(sp);
        
                WARN_ON(!sept_page);
                WARN_ON(sp->role.level + 1 != change->level);
                WARN_ON(sp->gfn != change->gfn);
                return kvm_mmu_private_sp(sp);
        }
        
        return NULL;
}               
```

The tdx_get_sept_page function retrieves this S-EPT physical address extracted 
from the new sp. Because the change only contains the pfn of the new spt, it 
first retrieves the sp (kvm_mmu_page) through the to_shadow_page function. Note
that the kvm_mmu_page bound to one spt can be retrieved from the private field 
of the spt physical address (please refer to [[]]). The kvm_mmu_private_sp 
simply returns private_sp field of the sp. The returned private_sp field is 
stored in sept_page field of the change variable. The private_sp field of sp 
points to the memory allocated at the time of sp initialization, prepared for 
S-EPT uses. Now the change variable can provide all required information to 
update the S-EPT in the TDX module side. Only the left operation is invoking 
proper SEAMCALL with provided parameters so that VMM makes the TDX module change
the S-EPT on behalf of the VMM.

```cpp
static void tdx_handle_private_zapped_spte(
        struct kvm *kvm, const struct kvm_spte_change *change)
{
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);

        WARN_ON(!is_td(kvm));
        WARN_ON(change->old.is_present);
        WARN_ON(!change->old.is_private_zapped);
        WARN_ON(change->new.is_private_zapped);

        /*
         * Handle special case of old_spte being temporarily blocked private
         * SPTE.  There are two cases: 1) Need to restore the original mapping
         * (unblock) when guest accesses the private page; 2) Need to truly
         * zap the SPTE because of zapping aliasing in fault handler, or when
         * VM is being destroyed.
         *
         * Do this before handling "!was_present && !is_present" case below,
         * because blocked private SPTE is also non-present.
         */
        if (change->new.is_present) {
                /* map_gpa holds write lock. */
                lockdep_assert_held(&kvm->mmu_lock);

                if (change->old.pfn == change->new.pfn) {
                        tdx_sept_unzap_private_spte(kvm, change->gfn, change->level);
                } else if (change->level > PG_LEVEL_4K &&
                           change->old.is_last && !change->new.is_last) {
                        int i;

                        /* This large SPTE is blocked already. */
                        tdx_sept_split_private_spte(kvm, change->gfn, change->level, change->sept_page);
                        /* Block on newly splited SPTEs as parent SPTE as blocked. */
                        for (i = 0; i < PT64_ENT_PER_PAGE; i++)
                                tdx_sept_zap_private_spte(kvm, change->gfn + i, change->level - 1);
                        tdx_sept_tlb_remote_flush(kvm);
                } else {
                        /*
                         * Because page is pined (refer to
                         * kvm_faultin_pfn_private()), page migration shouldn't
                         * be triggered for private page.  kvm private memory
                         * slot case should also prevent page migration.
                         */
                        pr_err("gfn 0x%llx level %d "
                               "old_pfn 0x%llx was_present %d was_last %d was_priavte_zapped %d "
                               "new_pfn 0x%llx is_present %d is_last %d is_priavte_zapped %d\n",
                               change->gfn, change->level,
                               change->old.pfn, change->old.is_present,
                               change->old.is_last, change->old.is_private_zapped,
                               change->new.pfn, change->new.is_present,
                               change->new.is_last, change->new.is_private_zapped);
                        WARN_ON(1);
                }
        } else {
                lockdep_assert_held_write(&kvm->mmu_lock);
                if (is_hkid_assigned(kvm_tdx))
                        tdx_track(kvm_tdx);
                tdx_sept_drop_private_spte(kvm, change->gfn, change->level,
                                        change->old.pfn);
        }
}
```

### kvm_x86_handle_changed_private_spte
```cpp
        /*
         * Special handling for the private mapping.  We are either
         * setting up new mapping at middle level page table, or leaf,
         * or tearing down existing mapping.
         *
         * This is after handling lower page table by above
         * handle_remove_tdp_mmu_page().  S-EPT requires to remove S-EPT tables
         * after removing childrens.
         */
        if (private_spte &&
            /* Ignore change of software only bits. e.g. host_writable */
            (was_leaf != is_leaf || was_present != is_present || pfn_changed ||
             was_private_zapped != is_private_zapped)) {
                change.sept_page = tdx_get_sept_page(&change);
                WARN_ON(was_private_zapped && is_private_zapped);
                /*
                 * When write lock is held, leaf pte should be zapping or
                 * prohibiting.  Not directly was_present=1 -> zero EPT entry.
                 */
                WARN_ON(!shared && is_leaf &&
                        !is_private_zapped);
                static_call(kvm_x86_handle_changed_private_spte)(kvm, &change);
        }

```

```cpp
static void tdx_handle_changed_private_spte(
        struct kvm *kvm, const struct kvm_spte_change *change)
{
        bool was_leaf = change->old.is_present && change->old.is_last;
        bool is_leaf = change->new.is_present && change->new.is_last;
        struct kvm_tdx *kvm_tdx = to_kvm_tdx(kvm);
        const gfn_t gfn = change->gfn;
        const enum pg_level level = change->level;

        WARN_ON(!is_td(kvm));
        lockdep_assert_held(&kvm->mmu_lock);

        if (change->new.is_present) {
                if (level > PG_LEVEL_4K && was_leaf && !is_leaf) {
                        tdx_sept_zap_private_spte(kvm, gfn, level);
                        tdx_sept_tlb_remote_flush(kvm);
                        tdx_sept_split_private_spte(kvm, gfn, level, change->sept_page);
                } else if (is_leaf)
                        tdx_sept_set_private_spte(
                                kvm, gfn, level, change->new.pfn);
                else {
                        WARN_ON(!change->sept_page);
                        if (tdx_sept_link_private_sp(
                                    kvm, gfn, level, change->sept_page))
                                /* failed to update Secure-EPT.  */
                                WARN_ON(1);
                }
        } else if (was_leaf) {
                /* non-present -> non-present doesn't make sense. */
                WARN_ON(!change->old.is_present);

                /*
                 * Zap private leaf SPTE.  Zapping private table is done
                 * below in handle_removed_tdp_mmu_page().
                 */
                tdx_sept_zap_private_spte(kvm, gfn, level);

                if (change->new.is_private_zapped) {
                        lockdep_assert_held_write(&kvm->mmu_lock);
                        WARN_ON(change->new.pfn != change->old.pfn);
                } else {
                        lockdep_assert_held_write(&kvm->mmu_lock);
                        WARN_ON(change->new.pfn);

                        /*
                         * TDX requires TLB tracking before dropping private
                         * page.
                         */
                        if (is_hkid_assigned(kvm_tdx))
                                tdx_track(kvm_tdx);

                        tdx_sept_drop_private_spte(kvm, gfn, level, change->old.pfn);
                }
        }
}
```

### kvm_x86_free_private_sp (handle_removed_pt)
```cpp
        /*
         * Recursively handle child PTs if the change removed a subtree from
         * the paging structure.  Note the WARN on the PFN changing without the
         * SPTE being converted to a hugepage (leaf) or being zapped.  Shadow
         * pages are kernel allocations and should never be migrated.
         */
        if (was_present && !was_last &&
            (is_leaf || !is_present || WARN_ON_ONCE(pfn_changed))) {
                WARN_ON(private_spte !=
                        is_private_sptep(spte_to_child_pt(old_spte, level)));
                handle_removed_pt(kvm, spte_to_child_pt(old_spte, level),
                                  private_spte, shared);
        }
```
This condition indicates that 
1. previous page is split into the leaf page
2. previous page is removed 
3. physical page for the spte is changed 

```cpp
static void handle_removed_pt(struct kvm *kvm, tdp_ptep_t pt, bool is_private,
                              bool shared)
{
        struct kvm_mmu_page *sp = sptep_to_sp(rcu_dereference(pt));
        int level = sp->role.level;
        gfn_t base_gfn = sp->gfn;
        int i;

        trace_kvm_mmu_prepare_zap_page(sp);

        tdp_mmu_unlink_sp(kvm, sp, shared);

        for (i = 0; i < PT64_ENT_PER_PAGE; i++) {
                tdp_ptep_t sptep = pt + i;
                gfn_t gfn = base_gfn + i * KVM_PAGES_PER_HPAGE(level);
                u64 old_spte;

                if (shared) {
                        /*
                         * Set the SPTE to a nonpresent value that other
                         * threads will not overwrite. If the SPTE was
                         * already marked as removed then another thread
                         * handling a page fault could overwrite it, so
                         * set the SPTE until it is set from some other
                         * value to the removed SPTE value.
                         */
                        for (;;) {
                                old_spte = kvm_tdp_mmu_write_spte_atomic(sptep, REMOVED_SPTE);
                                if (!is_removed_spte(old_spte))
                                        break;
                                cpu_relax();
                        }
                } else {
                        /*
                         * If the SPTE is not MMU-present, there is no backing
                         * page associated with the SPTE and so no side effects
                         * that need to be recorded, and exclusive ownership of
                         * mmu_lock ensures the SPTE can't be made present.
                         * Note, zapping MMIO SPTEs is also unnecessary as they
                         * are guarded by the memslots generation, not by being
                         * unreachable.
                         */
                        old_spte = kvm_tdp_mmu_read_spte(sptep);
                        /*
                         * It comes here when zapping all pages when destroying
                         * vm.  It means TLB shootdown optimization doesn't make
                         * sense.  Zap private_zapped entry.
                         */
                        if (!is_shadow_present_pte(old_spte) &&
                            !is_private_zapped_spte(old_spte))
                                continue;

                        /*
                         * Use the common helper instead of a raw WRITE_ONCE as
                         * the SPTE needs to be updated atomically if it can be
                         * modified by a different vCPU outside of mmu_lock.
                         * Even though the parent SPTE is !PRESENT, the TLB
                         * hasn't yet been flushed, and both Intel and AMD
                         * document that A/D assists can use upper-level PxE
                         * entries that are cached in the TLB, i.e. the CPU can
                         * still access the page and mark it dirty.
                         *
                         * No retry is needed in the atomic update path as the
                         * sole concern is dropping a Dirty bit, i.e. no other
                         * task can zap/remove the SPTE as mmu_lock is held for
                         * write.  Marking the SPTE as a removed SPTE is not
                         * strictly necessary for the same reason, but using
                         * the remove SPTE value keeps the shared/exclusive
                         * paths consistent and allows the handle_changed_spte()
                         * call below to hardcode the new value to REMOVED_SPTE.
                         *
                         * Note, even though dropping a Dirty bit is the only
                         * scenario where a non-atomic update could result in a
                         * functional bug, simply checking the Dirty bit isn't
                         * sufficient as a fast page fault could read the upper
                         * level SPTE before it is zapped, and then make this
                         * target SPTE writable, resume the guest, and set the
                         * Dirty bit between reading the SPTE above and writing
                         * it here.
                         */
                        old_spte = kvm_tdp_mmu_write_spte(sptep, old_spte,
                                                          REMOVED_SPTE, level);
                }
                handle_changed_spte(kvm, kvm_mmu_page_as_id(sp), gfn, is_private,
                                    old_spte, REMOVED_SPTE, level,
                                    shared);
        }

        WARN_ON(is_private && !kvm_mmu_private_sp(sp));
        if (is_private && WARN_ON(static_call(kvm_x86_free_private_sp)(
                                          kvm, sp->gfn, sp->role.level,
                                          kvm_mmu_private_sp(sp)))) {
                /*
                 * Failed to unlink Secure EPT page and there is nothing to do
                 * further.  Intentionally leak the page to prevent the kernel
                 * from accessing the encrypted page.
                 */
                kvm_mmu_init_private_sp(sp, NULL);
        }

        call_rcu(&sp->rcu_head, tdp_mmu_free_sp_rcu_callback);
}


```





