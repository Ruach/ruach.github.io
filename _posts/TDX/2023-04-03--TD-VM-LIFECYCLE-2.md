---
layout: post
title: "TD VM Life Cycle Part 2"
categories: [Confidential Computing, Intel TDX]
---


# Deep dive into TD VCPU creation (TDH_VP_CREATE-TDH_VP_INIT)
## Instantiating TD VCPU
After the VM has been initialized, note that it has not been finalized yet, it 
can generate VCPUs assigned to the generated TD instance. The logistics of TD 
VCPU generation consists of two parts mainly: generate VCPU (KVM_CREATE_VCPU) 
and initialize the generated VCPU as TDX VCPU (KVM_TDX_INIT_VCPU) through 
the SEAMCALL, TDH_VP_INIT.

### VCPU Creation for TDX 
The first step is generating VCPU instance as we do for vanilla VM's VCPU. It 
utilizes the same interface from QEMU side, KVM_CREATE_VCPU of the kvm_vm_ioctl.
kvm_vm_ioctl_create_vcpu is the main function handling the ioctl and invokes 
following functions to initialize the VCPU related features including MMU.
MMU initialization details are described in [here].

```cpp
10997 int kvm_arch_vcpu_create(struct kvm_vcpu *vcpu)
......
        r = static_call(kvm_x86_vcpu_create)(vcpu);
        if (r)
                goto free_guest_fpu;

        vcpu->arch.arch_capabilities = kvm_get_arch_capabilities();
        vcpu->arch.msr_platform_info = MSR_PLATFORM_INFO_CPUID_FAULT;
        kvm_xen_init_vcpu(vcpu);
        kvm_vcpu_mtrr_init(vcpu);
        vcpu_load(vcpu);
        kvm_set_tsc_khz(vcpu, vcpu->kvm->arch.default_tsc_khz);
        kvm_vcpu_reset(vcpu, false);
        kvm_init_mmu(vcpu);
        vcpu_put(vcpu);
        return 0;

```

kvm_arch_vcpu_create is the architecture specific VCPU initialization function.
```cpp
struct kvm_x86_ops vt_x86_ops __initdata = {
        .vcpu_create = vt_vcpu_create,
```
```cpp
static int vt_vcpu_create(struct kvm_vcpu *vcpu)
{
        if (is_td_vcpu(vcpu))
                return tdx_vcpu_create(vcpu);

        return vmx_vcpu_create(vcpu);
}
```
And the kvm_x86_vcpu_create function, actually the tdx_vcpu_create function 
generates the TD VM's VCPU instances. 

### Trust Domain Virtual Processor State (TDVPS)
>Trust Domain Virtual Processor Root (TDVPR) is the 4KB root page of TDVPS. Its 
>physical address serves as a **unique identifier of the VCPU** (as long as it 
>resides in memory).

As the TDR is the id of the TD VM, each TD VCPU requires associated TDX metadata
called **Trust Domain Virtual Processor State (TDVPS)**. For example, **TD VCPU 
and TD VMCS** structure are stored in the TDVPS as shown in the figure.

![TDVPS](/assets//img/TDX/TDVPS.png)

>Trust Domain Virtual Processor eXtension (TDVPX) 4KB pages extend TDVPR to help
>provide enough physical space for the logical TDVPS structure.

TDX **logically** views the TDVPS as a consecutive memory region containing all 
VMX standard control structure such as TD VMCS and TD VCPU. Especially, TD VCPU 
Management fields manage the operation of the VCPU. However, **physically**, it 
consists of multiple physical pages represented as **TDVPR root page and TDVPX 
child pages**. 

>The required number of 4KB TDVPR/TDVPX pages in TDVPS is enumerated to the VMM
>by the TDH.SYS.INFO function.

### TDVPS management in TDX Module
```cpp
typedef struct tdvps_management_s
{
    uint8_t   state; /**< The activity state of the VCPU */
    /**
     * A boolean flag, indicating whether the TD VCPU has been VMLAUNCH’ed
     * on this LP since it has last been associated with this VCPU. If TRUE,
     * VM entry should use VMRESUME. Else, VM entry should use VMLAUNCH.
     */
    bool_t    launched;
    /**
     * Sequential index of the VCPU in the parent TD. VCPU_INDEX indicates the order
     * of VCPU initialization (by TDHVPINIT), starting from 0, and is made available to
     * the TD via TDINFO. VCPU_INDEX is in the range 0 to (MAX_VCPUS_PER_TD - 1)
     */
    uint32_t  vcpu_index;
    uint8_t   num_tdvpx; /**< A counter of the number of child TDVPX pages associated with this TDVPR */

    uint8_t   reserved_0[1]; /**< Reserved for aligning the next field */
    /**
     * An array of (TDVPS_PAGES) physical address pointers to the TDVPX pages
     *
     * PA is without HKID bits
     * Page 0 is the PA of the TDVPR page
     * Pages 1,2,... are PAs of the TDVPX pages
    */
    uint64_t  tdvps_pa[MAX_TDVPS_PAGES];
    /**
     * The (unique hardware-derived identifier) of the logical processor on which this VCPU
     * is currently associated (either by TDHVPENTER or by other VCPU-specific SEAMCALL flow).
     * A value of 0xffffffff (-1 in signed) indicates that VCPU is not associated with any LP.
     * Initialized by TDHVPINIT to the LP_ID on which it ran
     */
    uint32_t  assoc_lpid;
    /**
     * The TD's ephemeral private HKID at the last time this VCPU was associated (either
     * by TDHVPENTER or by other VCPU-specific SEAMCALL flow) with an LP.
     * Initialized by TDHVPINIT to the current TD ephemeral private HKID.
     */
    uint32_t  assoc_hkid;
    /**
     * The value of TDCS.TD_EPOCH, sampled at the time this VCPU entered TDX non-root mode
     */
    uint64_t  vcpu_epoch;

    bool_t    cpuid_supervisor_ve;
    bool_t    cpuid_user_ve;
    bool_t    is_shared_eptp_valid;

    uint8_t   reserved_1[5]; /**< Reserved for aligning the next field */

    uint64_t  last_exit_tsc;

    bool_t    pend_nmi;

    uint8_t   reserved_2[7]; /**< Reserved for aligning the next field */

    uint64_t  xfam;
    uint8_t   last_epf_gpa_list_idx;
    uint8_t   possibly_epf_stepping;

    uint8_t   reserved_3[150]; /**< Reserved for aligning the next field */

    uint64_t   last_epf_gpa_list[EPF_GPA_LIST_SIZE];  // Array of GPAs that caused EPF at this TD vCPU instruction

    uint8_t   reserved_4[256]; /**< Reserved for aligning the next field */
} tdvps_management_t;
```


### Allocating TDVPR page and TDVPX pages
VMM should prepare TDVPR and TDVPX pages before it bounds the pages to the VCPU.
tdx_vcpu_create function allocate one TDVPR page and multiple TDVPX pages.

```cpp
634 int tdx_vcpu_create(struct kvm_vcpu *vcpu)
635 {
......
648         ret = tdx_alloc_td_page(&tdx->tdvpr);
649         if (ret)
650                 return ret;
651 
652         tdx->tdvpx = kcalloc(tdx_caps.tdvpx_nr_pages, sizeof(*tdx->tdvpx),
653                         GFP_KERNEL_ACCOUNT);
654         if (!tdx->tdvpx) {
655                 ret = -ENOMEM;
656                 goto free_tdvpr;
657         }
658         for (i = 0; i < tdx_caps.tdvpx_nr_pages; i++) {
659                 ret = tdx_alloc_td_page(&tdx->tdvpx[i]);
660                 if (ret)
661                         goto free_tdvpx;
662         }
```

To utilize the created VCPU, the TDX VM should have a **TDVPR** page bound to 
the VCPU assigned to the TD VM. Physical page for TDVPR is allocated when VCPU 
is created. Also note that it allocates multiple physical pages for TDVPX. The
generated TDVPR is used when registering the generated VCPU to specific TD VM 
through TDH_VP_CREATE, which adds a TDVPR page as a child of a TDR page. Also, 
TDH.VP.ADDCX adds a TDVPX page as a child of a given TDVPR (tdh_vp_addcx). We 
will cover when and how the TDVPX pages are initialized based on their semantics
as VMCS for example. 


### Create VCPU for TD VM
Note that we haven't generated any VCPU instance, but TDVPS page required for
generating TDX VPCU instance. Because the TD VCPU should be belong to one TD VM,
it requires TDR page to denote which TD VM will have the access for the newly 
generated TD VCPU. You will see that TDH_VP_CREATE SEAMCALL receive these two 
data structures to instantiate new VCPU for TDX.


```cpp
11148 void kvm_vcpu_reset(struct kvm_vcpu *vcpu, bool init_event)
......
11230         static_call(kvm_x86_vcpu_reset)(vcpu, init_event);
```

```cpp
 992 static struct kvm_x86_ops vt_x86_ops __initdata = {
......
1008         .vcpu_reset = vt_vcpu_reset,
```

```cpp
 169 static void vt_vcpu_reset(struct kvm_vcpu *vcpu, bool init_event)
 170 {
 171         if (is_td_vcpu(vcpu))
 172                 return tdx_vcpu_reset(vcpu, init_event);
 173 
 174         return vmx_vcpu_reset(vcpu, init_event);
 175 }
```

If current kvm_vcpu indicates that it is VCPU for TD-VM, it invokes 
tdx_vcpu_reset function that calls TDH_VP_CREATE SEAMCALL.

```cpp
 825 void tdx_vcpu_reset(struct kvm_vcpu *vcpu, bool init_event)
 826 {
 ......
 839         err = tdh_vp_create(kvm_tdx->tdr.pa, tdx->tdvpr.pa);
 840         if (WARN_ON_ONCE(err)) {
 841                 pr_tdx_error(TDH_VP_CREATE, err, NULL);
 842                 goto td_bugged;
 843         }
 844         tdx_mark_td_page_added(&tdx->tdvpr);
 845 
 846         for (i = 0; i < tdx_caps.tdvpx_nr_pages; i++) {
 847                 err = tdh_vp_addcx(tdx->tdvpr.pa, tdx->tdvpx[i].pa);
 848                 if (WARN_ON_ONCE(err)) {
 849                         pr_tdx_error(TDH_VP_ADDCX, err, NULL);
 850                         goto td_bugged;
 851                 }
 852                 tdx_mark_td_page_added(&tdx->tdvpx[i]);
 853         }
```

The TDH_VP_CREATE SEAMCALL creates the VCPU by registering TDVPR page as a child
of TDR. Note that TDR page is owned by the TDX module, so the TDX module should 
register the TDVPR page as its child. After the TDVPR page is added, because it
is a logical concept, additional TDVPX pages should be added in addition to the 
first TDVPR page by TDH_VP_ADDCX SEAMCALL.

### TDX_VP_CREATE (TDX Module side)
Because the TDVPR page address is passed from VMM, it needs to be converted into
private page of the TD VM. We already covered how this conversion is done by the
TDX module ([XXX]). After the private mapping is created, the TDVPR page should 
be initialized and registered as a child of TDR. Through this process, the TD
VCPU is created and bound to specific TD VM.

```cpp
api_error_type tdh_vp_create(uint64_t target_tdvpr_pa, uint64_t target_tdr_pa)
{
    ......
    // Check, lock and map the new TDVPR page
    return_val = check_lock_and_map_explicit_private_4k_hpa(tdvpr_pa,
                                                            OPERAND_ID_RCX,
                                                            tdr_ptr,
                                                            TDX_RANGE_RW,
                                                            TDX_LOCK_EXCLUSIVE,
                                                            PT_NDA,
                                                            &tdvpr_pamt_block,
                                                            &tdvpr_pamt_entry_ptr,
                                                            &tdvpr_locked_flag,
                                                            (void**)&tdvps_ptr);

    ......
    tdvps_ptr->management.assoc_lpid = (uint32_t)-1;
    tdvps_ptr->management.tdvps_pa[0] = tdvpr_pa.raw;

    // Register the new TDVPR page in its owner TDR
    _lock_xadd_64b(&(tdr_ptr->management_fields.chldcnt), 1);

    // Set the new TDVPR page PAMT fields
    tdvpr_pamt_entry_ptr->pt = PT_TDVPR;
    set_pamt_entry_owner(tdvpr_pamt_entry_ptr, tdr_pa);
```


### TDH_VP_ADDCX (TDX Module side)
Physically the TDVPR page consists of multiple TDVPX pages, and the TDH_VP_ADDCX
adds the TDVPX page as the child of TDVPR. Note that this function receives the 
TDVPR and TDVPX page not the TDR page. 

```cpp
api_error_type tdh_vp_addcx(uint64_t target_tdvpx_pa, uint64_t target_tdvpr_pa)
{
    ......
    // Check and lock the parent TDVPR page
    return_val = check_and_lock_explicit_4k_private_hpa(tdvpr_pa,
                                                         OPERAND_ID_RDX,
                                                         TDX_LOCK_EXCLUSIVE,
                                                         PT_TDVPR,
                                                         &tdvpr_pamt_block,
                                                         &tdvpr_pamt_entry_ptr,
                                                         &page_leaf_size,
                                                         &tdvpr_locked_flag);
    // Get and lock the owner TDR page                   
    tdr_pa = get_pamt_entry_owner(tdvpr_pamt_entry_ptr); 
    return_val = lock_and_map_implicit_tdr(tdr_pa,       
                                           OPERAND_ID_TDR,
                                           TDX_RANGE_RW, 
                                           TDX_LOCK_SHARED,
                                           &tdr_pamt_entry_ptr,
                                           &tdr_locked_flag,
                                           &tdr_ptr);
    ......
    // Map the TDVPS structure.  Note that only the 1st page (TDVPR) is
    // accessible at this point.
    tdvps_ptr = (tdvps_t*)map_pa((void*)(set_hkid_to_pa(tdvpr_pa, td_hkid).full_pa), TDX_RANGE_RW);

    ......
    // Check, lock and map the new TDVPX page
    return_val = check_lock_and_map_explicit_private_4k_hpa(tdvpx_pa,
                                                            OPERAND_ID_RCX,
                                                            tdr_ptr,
                                                            TDX_RANGE_RW,
                                                            TDX_LOCK_EXCLUSIVE,
                                                            PT_NDA,
                                                            &tdvpx_pamt_block,
                                                            &tdvpx_pamt_entry_ptr,
                                                            &tdvpx_locked_flag,
                                                            (void**)&tdvpx_ptr);
    ......
    // Clear the content of the TDVPX page using direct writes
    zero_area_cacheline(tdvpx_ptr, TDX_PAGE_SIZE_IN_BYTES);

    // Register the new TDVPX in its parent TDVPS structure
    // Note that tdvpx_pa[0] is the PA of TDVPR, so TDVPX
    // pages start from index 1
    tdvpx_index_num++;
    tdvps_ptr->management.num_tdvpx = (uint8_t)tdvpx_index_num;
    tdvps_ptr->management.tdvps_pa[tdvpx_index_num] = tdvpx_pa.raw;

    // Register the new TDVPX page in its owner TDR
    _lock_xadd_64b(&(tdr_ptr->management_fields.chldcnt), 1);

    // Set the new TDVPX page PAMT fields
    tdvpx_pamt_entry_ptr->pt = PT_TDVPX;
    set_pamt_entry_owner(tdvpx_pamt_entry_ptr, tdr_pa);
```

Because the TDVPR page has been initialized and registered as a private page for
the TD VM before in the TDH_VP_CREATE SEMCALL, its corresponding PAMT block will
be also retrieved as a result of the check_and_lock_explicit_4k_private_hpa func.
Because each PAMT entry memorize owner TD VM where the physical address mapped 
by the PAMT belongs to, it can easily retrieve its owner, the TDR. It also maps 
TDVPR and TDVPX, but because TDVPX is mapped to private page first time, mapping
is done by map_pa and check_lock_and_map_explicit_private_4k_hpa, respectively.
It updates the TDVPR and initialize TDVPX page. Note that still each TDVPX page
is not initialized. We will see how each TDVPX page will be initialized to carry
VCPU information. 



### Initialize registered VCPU (TDH_VP_INIT)
After adding all VCPU related physical pages to the TD VM, it is ready for VCPU
initialization. When the TDX module finish initialization of VCPU of the TD VM, 
the status of the VM is changed to **initialized**.

```cpp
2472 static int tdx_vcpu_ioctl(struct kvm_vcpu *vcpu, void __user *argp)
......
2488         if (cmd.metadata || cmd.id != KVM_TDX_INIT_VCPU)
2489                 return -EINVAL;
2490 
2491         err = tdh_vp_init(tdx->tdvpr.pa, cmd.data);
2492         if (TDX_ERR(err, TDH_VP_INIT, NULL))
2493                 return -EIO;
2494 
2495         tdx->initialized = true;
2496 
2497         td_vmcs_write16(tdx, POSTED_INTR_NV, POSTED_INTR_VECTOR);
2498         td_vmcs_write64(tdx, POSTED_INTR_DESC_ADDR, __pa(&tdx->pi_desc));
2499         td_vmcs_setbit32(tdx, PIN_BASED_VM_EXEC_CONTROL, PIN_BASED_POSTED_INTR);
```
It invokes tdh_vp_init function which invokes TDH_VP_INIT SEAMCALL. We can say 
that The VCPU initialization is equal to TDVPR page initialization. Let's see 
how TDX Module initializes the TDVPR pages and related data structures used to 
manage TDVPS.


### Initialize TDVPS page
```cpp
typedef enum
{   
    TDVPS_VE_INFO_PAGE_INDEX = 0,
    TDVPS_VMCS_PAGE_INDEX    = 1,
    TDVPS_VAPIC_PAGE_INDEX   = 2,
    MAX_TDVPS_PAGES          = 6
} tdvps_pages_e;

typedef struct ALIGN(TDX_PAGE_SIZE_IN_BYTES) tdvps_s            
{   
    tdvps_ve_info_t                ve_info;
    uint8_t                        reserved_0[128]; /**< Reserved for aligning the next field */
    tdvps_management_t             management;
    tdvps_guest_state_t            guest_state;
    tdvps_guest_msr_state_t        guest_msr_state;
    
    uint8_t                        reserved_1[2432]; /**< Reserved for aligning the next field */
    
    tdvps_td_vmcs_t                td_vmcs;
    uint8_t                        reserved_2[TDX_PAGE_SIZE_IN_BYTES - SIZE_OF_TD_VMCS_IN_BYTES]; /**< Reserved for aligning the next field */

    tdvps_vapic_t                  vapic;
    tdvps_guest_extension_state_t  guest_extension_state;
} tdvps_t;
```

TDVPS page can semantically be divided into 3 different pages as shown in the 
tdvps_pages_e: VE_INFO, VMCS, VAPIC page. Let's see how TDX Module functions 
initialize those three pages as a part of TDH_VP_INIT SEAMCALL.


```cpp
api_error_type tdh_vp_init(uint64_t target_tdvpr_pa, uint64_t td_vcpu_rcx)
{
    ......
    // Get the TD's ephemeral HKID
    curr_hkid = tdr_ptr->key_management_fields.hkid;

    // Map the multi-page TDVPS structure
    tdvps_ptr = map_tdvps(tdvpr_pa, curr_hkid, TDX_RANGE_RW);
    ......

    /**
     *  Initialize the TD VCPU GPRs.  Default GPR value is 0.
     *  Initialize the TD VCPU non-GPR register state in TDVPS:
     *  CRs, DRs, XCR0, IWK etc.
     */
    init_vcpu_gprs_and_registers(tdvps_ptr, tdcs_ptr, init_rcx, vcpu_index);

    /**
     *  Initialize the TD VCPU MSR state in TDVPS
     */
    init_vcpu_msrs(tdvps_ptr);

    /**
     *  No need to explicitly initialize TD VCPU extended state pages.
     *  Since the pages are initialized to 0 on TDHVPCREATE/TDVPADDCX.
     */

    // Bit 63 of XCOMP_BV should be set to 1, to indicate compact format.
    // Otherwise XSAVES and XRSTORS won't work
    tdvps_ptr->guest_extension_state.xbuf.xsave_header.xcomp_bv = BIT(63);

    // Initialize TDVPS.LBR_DEPTH to MAX_LBR_DEPTH supported on the core
    if (((ia32_xcr0_t)tdcs_ptr->executions_ctl_fields.xfam).lbr)
    {
        tdvps_ptr->guest_msr_state.ia32_lbr_depth = (uint64_t)get_global_data()->max_lbr_depth;
    }
    /**
     *  No need to explicitly initialize VAPIC page.
     *  Since the pages are initialized to 0 on TDHVPCREATE/TDVPADDCX,
     *  VAPIC page is already 0.
     */
```
Note that it receives cmd.data which will be set as an initial RCX value of the
VCPU. This RCX value will be used when VBIOS initially starts from TD VM. 

```cpp

_STATIC_INLINE_ void init_vcpu_gprs_and_registers(tdvps_t * tdvps_ptr, tdcs_t * tdcs_ptr, uint64_t init_rcx, uint32_t vcpu_index)
{
    /**
     *  GPRs init
     */
    if (tdcs_ptr->executions_ctl_fields.gpaw)
    {
        tdvps_ptr->guest_state.rbx = MAX_PA_FOR_GPAW;
    }
    else
    {
        tdvps_ptr->guest_state.rbx = MAX_PA_FOR_GPA_NOT_WIDE;
    }
    // Set RCX and R8 to the input parameter's value
    tdvps_ptr->guest_state.rcx = init_rcx;
    tdvps_ptr->guest_state.r8 = init_rcx;

    // CPUID(1).EAX - returns Family/Model/Stepping in EAX - take the saved value by TDHSYSINIT
    tdx_debug_assert(get_cpuid_lookup_entry(0x1, 0x0) < MAX_NUM_CPUID_LOOKUP);
    tdvps_ptr->guest_state.rdx = (uint64_t)get_global_data()->cpuid_values[get_cpuid_lookup_entry(0x1, 0x0)].values.eax;

    /**
     *  Registers init
     */
    tdvps_ptr->guest_state.xcr0 = XCR0_RESET_STATE;
    tdvps_ptr->guest_state.dr6 = DR6_RESET_STATE;


    // Set RSI to the VCPU index
    tdvps_ptr->guest_state.rsi = vcpu_index & BITS(31,0);

    /**
     *  All other GPRs/Registers are set to 0 or
     *  that their INIT state is 0
     *  Doesn’t include values initialized in VMCS
     */
}
```


### VMCS initialization
The most important page of the TDVPS is VMCS of the TD VCPU. It is literally 
identical with the VMCS for vanilla VM VCPU. Let's see how the TDX Module sets
up VMCS structure for TD VCPU.


```cpp
    vmcs_pa = set_hkid_to_pa((pa_t)tdvps_ptr->management.tdvps_pa[TDVPS_VMCS_PAGE_INDEX], curr_hkid);

    /**
     *  Map the TD VMCS page.
     *
     *  @note This is the only place the VMCS page is directly accessed.
     */
    vmcs_ptr = map_pa((void*)vmcs_pa.raw, TDX_RANGE_RW);
    vmcs_ptr->revision.vmcs_revision_identifier =
            get_global_data()->plt_common_config.ia32_vmx_basic.vmcs_revision_id;

    // Clear the TD VMCS
    ia32_vmclear((void*)vmcs_pa.raw);

    /**
     *  No need to explicitly initialize VE_INFO.
     *  Since the pages are initialized to 0 on TDHVPCREATE/TDVPADDCX,
     *  VE_INFO.VALID is already 0.
     */

    // Mark the VCPU as initialized and ready
    tdvps_ptr->management.state = VCPU_READY_ASYNC;

    /**
     *  Save the host VMCS fields before going to TD VMCS context
     */
    save_vmcs_host_fields(&td_vmcs_host_values);


    /**
     *  Associate the VCPU - no checks required
     */
    associate_vcpu_initial(tdvps_ptr, tdcs_ptr, tdr_ptr, &td_vmcs_host_values);
    td_vmcs_loaded = true;

    /**
     *  Initialize the TD VMCS fields
     */
    init_td_vmcs(tdcs_ptr, tdvps_ptr, &td_vmcs_host_values);
```

Because TDX Module doesn't manage the virtual mapping of all physical pages of 
the meta data of one TD VM, it should be mapped first and should retrieve a 
virtual address for TD VMCS page. The management structure maintain physical 
pages of the TDVPS pages. After the mapping is done, init_td_vmcs initializes 
VMCS for TD VCPU.


```cpp
void save_vmcs_host_fields(vmcs_host_values_t* host_fields_ptr)
{   
    read_vmcs_field_info(VMX_HOST_CR0_ENCODE, &host_fields_ptr->CR0);
    read_vmcs_field_info(VMX_HOST_CR3_ENCODE, &host_fields_ptr->CR3);
    read_vmcs_field_info(VMX_HOST_CR4_ENCODE, &host_fields_ptr->CR4);
    read_vmcs_field_info(VMX_HOST_CS_SELECTOR_ENCODE, &host_fields_ptr->CS);
    read_vmcs_field_info(VMX_HOST_SS_SELECTOR_ENCODE, &host_fields_ptr->SS);
    read_vmcs_field_info(VMX_HOST_FS_SELECTOR_ENCODE, &host_fields_ptr->FS);
    read_vmcs_field_info(VMX_HOST_GS_SELECTOR_ENCODE, &host_fields_ptr->GS);
    read_vmcs_field_info(VMX_HOST_TR_SELECTOR_ENCODE, &host_fields_ptr->TR);
    read_vmcs_field_info(VMX_HOST_IA32_S_CET_ENCODE, &host_fields_ptr->IA32_S_CET);
    read_vmcs_field_info(VMX_HOST_SSP_ENCODE, &host_fields_ptr->SSP);
    read_vmcs_field_info(VMX_HOST_IA32_PAT_FULL_ENCODE, &host_fields_ptr->IA32_PAT);
    read_vmcs_field_info(VMX_HOST_IA32_EFER_FULL_ENCODE, &host_fields_ptr->IA32_EFER);
    read_vmcs_field_info(VMX_HOST_FS_BASE_ENCODE, &host_fields_ptr->FS_BASE);
    read_vmcs_field_info(VMX_HOST_RSP_ENCODE, &host_fields_ptr->RSP);
    read_vmcs_field_info(VMX_HOST_GS_BASE_ENCODE, &host_fields_ptr->GS_BASE);
}            
```

VMCS needs to be configured for two interfaces, host to VM and VM to host. The 
all required information to control VM to host interface is maintained by the 
TDX Module. Recall that we are still in the VMX root operation while the TDX 
Module executes. Also, **VMREAD** instruction reads from the current VMCS when 
the processor runs as VMX root operation. If executed in VMX non-root operation, 
the instruction reads from the VMCS referenced by the VMCS link pointer field in
the current VMCS.


```cpp
void associate_vcpu_initial(tdvps_t * tdvps_ptr,
                            tdcs_t * tdcs_ptr,
                            tdr_t * tdr_ptr,
                            vmcs_host_values_t * host_values)
{
    uint32_t         curr_lp_id = get_local_data()->lp_info.lp_id;
    uint16_t         curr_hkid;
    pa_t             vmcs_addr;
    
    tdvps_ptr->management.assoc_lpid = curr_lp_id;
    
        
    curr_hkid = tdr_ptr->key_management_fields.hkid;
    
    // Set the TD VMCS as the current VMCS
    vmcs_addr = set_hkid_to_pa((pa_t)tdvps_ptr->management.tdvps_pa[TDVPS_VMCS_PAGE_INDEX], curr_hkid);
        
    ia32_vmptrld((void*)vmcs_addr.raw);
    
    /**
     *  Update multiple TD VMCS physical address fields with the new HKID.
     */ 
    init_guest_td_address_fields(tdr_ptr, tdvps_ptr, curr_hkid);
    
    /**
     *  Update the TD VMCS LP-dependent host state fields.
     *  Applicable fields are HOST_RSP, HOST_SSP and HOST_GS_BASE
     */ 
    ia32_vmwrite(host_values->RSP.encoding, host_values->RSP.value);
    ia32_vmwrite(host_values->SSP.encoding, host_values->SSP.value);
    ia32_vmwrite(host_values->GS_BASE.encoding, host_values->GS_BASE.value);

    // Atomically increment the number of associated VCPUs
    _lock_xadd_32b(&(tdcs_ptr->management_fields.num_assoc_vcpus), 1);
}
```

To initialize the TD VMCS of the target TD, the VMCS should be first loaded into
the processor. It retrieves the VMCS from the tdvps and run **vmptrld** inst to 
switch VCPU of TDX Module to VCPU of TD VM. 

After switching the VCPU the most of the VCPU initialization is done by the func
init_td_vmcs. I will not cover the details, but previously stored host registers
SEAM VMCS will be written to TD VMCS's host registers because VM EXIT from the 
TD should jump to the TDX Module. Also the initialization includes private EPTP.
Note that the EPTP address is stored in the TDCS (refer to [part 1]({% post_url 2023-04-01-TD-VM-LIFECYCLE-1  %})). 
However, note that the entire EPTP has not been initialized, but the root. 

```cpp
#define VMX_GUEST_EPT_POINTER_FULL_ENCODE  0x201AULL
#define VMX_GUEST_EPT_POINTER_HIGH_ENCODE  0x201bULL
#define VMX_GUEST_SHARED_EPT_POINTER_FULL_ENCODE  0x203C
#define VMX_GUEST_SHARED_EPT_POINTER_HIGH_ENCODE  0x203D
```

Also, note that there are two different types of EPTP for TD VM. For that VMCS 
needs to be updated to contain pointers of shared and private EPTP. The private 
EPTP should be protected from the non-TD software layers, so it should be 
initialized by the TDX Module and written to VMCS through TDH_VP_INIT. However,
the shared EPTP is provided by the Host VMM (see detail in [part 3]({% post_url 2023-04-05-TD-VM-LIFECYCLE-3  %})), 
and it doesn't need to be secure. The purpose of shared EPTP is for sharing data
with host VMM. Therefore, another SEAMCALL is used to write the VMCS located in t
he TDX memory (TDH.VP.WR). 


## Read Write to TD VMCS from Host VMM 
Based on the debugging mode or production mode, TDX allows the VMM to read/write
some pages belong to TD VM, for example, TDVPS and VMCS. For this, TDX provides 
two SEAMCALL: TDH.VP.RD and TDH.VP.WR. To utilize the two SEAMCALL, KVM defines
below macro functions. 


```cpp
199 #define TDX_BUILD_TDVPS_ACCESSORS(bits, uclass, lclass)                        \
200 static __always_inline u##bits td_##lclass##_read##bits(struct vcpu_tdx *tdx,  \
201                                                         u32 field)             \
202 {                                                                              \
203         struct tdx_ex_ret ex_ret;                                              \
204         u64 err;                                                               \
205                                                                                \
206         tdvps_##lclass##_check(field, bits);                                   \
207         err = tdh_vp_rd(tdx->tdvpr.pa, TDVPS_##uclass(field), &ex_ret);        \
208         if (unlikely(err)) {                                                   \
209                 pr_err("TDH_VP_RD["#uclass".0x%x] failed: %s (0x%llx)\n",      \
210                        field, tdx_seamcall_error_name(err), err);              \
211                 return 0;                                                      \
212         }                                                                      \
213         return (u##bits)ex_ret.regs.r8;                                        \
214 }                                                                              \
215 static __always_inline void td_##lclass##_write##bits(struct vcpu_tdx *tdx,    \
216                                                       u32 field, u##bits val)  \
217 {                                                                              \
218         struct tdx_ex_ret ex_ret;                                              \
219         u64 err;                                                               \
220                                                                                \
221         tdvps_##lclass##_check(field, bits);                                   \
222         err = tdh_vp_wr(tdx->tdvpr.pa, TDVPS_##uclass(field), val,             \
223                       GENMASK_ULL(bits - 1, 0), &ex_ret);                      \
224         if (unlikely(err))                                                     \
225                 pr_err("TDH_VP_WR["#uclass".0x%x] = 0x%llx failed: %s (0x%llx)\n", \
226                        field, (u64)val, tdx_seamcall_error_name(err), err);    \
227 }                                                                              \
228 static __always_inline void td_##lclass##_setbit##bits(struct vcpu_tdx *tdx,   \
229                                                        u32 field, u64 bit)     \
230 {                                                                              \
231         struct tdx_ex_ret ex_ret;                                              \
232         u64 err;                                                               \
233                                                                                \
234         tdvps_##lclass##_check(field, bits);                                   \
235         err = tdh_vp_wr(tdx->tdvpr.pa, TDVPS_##uclass(field), bit, bit,        \
236                         &ex_ret);                                              \
237         if (unlikely(err))                                                     \
238                 pr_err("TDH_VP_WR["#uclass".0x%x] |= 0x%llx failed: %s (0x%llx)\n", \
239                        field, bit, tdx_seamcall_error_name(err), err);         \
240 }                                                                              \
241 static __always_inline void td_##lclass##_clearbit##bits(struct vcpu_tdx *tdx, \
242                                                          u32 field, u64 bit)   \
243 {                                                                              \
244         struct tdx_ex_ret ex_ret;                                              \
245         u64 err;                                                               \
246                                                                                \
247         tdvps_##lclass##_check(field, bits);                                   \
248         err = tdh_vp_wr(tdx->tdvpr.pa, TDVPS_##uclass(field), 0, bit,          \
249                         &ex_ret);                                              \
250         if (unlikely(err))                                                     \
251                 pr_err("TDH_VP_WR["#uclass".0x%x] &= ~0x%llx failed: %s (0x%llx)\n", \
252                        field, bit, tdx_seamcall_error_name(err), err);         \
253 }
254
255 TDX_BUILD_TDVPS_ACCESSORS(16, VMCS, vmcs);
256 TDX_BUILD_TDVPS_ACCESSORS(32, VMCS, vmcs);
257 TDX_BUILD_TDVPS_ACCESSORS(64, VMCS, vmcs);
258 
259 TDX_BUILD_TDVPS_ACCESSORS(64, APIC, apic);
260 TDX_BUILD_TDVPS_ACCESSORS(64, GPR, gpr);
261 TDX_BUILD_TDVPS_ACCESSORS(64, DR, dr);
262 TDX_BUILD_TDVPS_ACCESSORS(64, STATE, state);
263 TDX_BUILD_TDVPS_ACCESSORS(64, STATE_NON_ARCH, state_non_arch);
264 TDX_BUILD_TDVPS_ACCESSORS(64, MSR, msr);
265 TDX_BUILD_TDVPS_ACCESSORS(8, MANAGEMENT, management);
```

The defined macro functions are also utilized by the vmread and vmwrite macro 
functions

```cpp
 19 #define VT_BUILD_VMCS_HELPERS(type, bits, tdbits)                          \
 20 static __always_inline type vmread##bits(struct kvm_vcpu *vcpu,            \
 21                                          unsigned long field)              \
 22 {                                                                          \
 23         if (unlikely(is_td_vcpu(vcpu))) {                                  \
 24                 if (KVM_BUG_ON(!is_debug_td(vcpu), vcpu->kvm))             \
 25                         return 0;                                          \
 26                 return td_vmcs_read##tdbits(to_tdx(vcpu), field);          \
 27         }                                                                  \
 28         return vmcs_read##bits(field);                                     \
 29 }                                                                          \
 30 static __always_inline void vmwrite##bits(struct kvm_vcpu *vcpu,           \
 31                                           unsigned long field, type value) \
 32 {                                                                          \
 33         if (unlikely(is_td_vcpu(vcpu))) {                                  \
 34                 if (KVM_BUG_ON(!is_debug_td(vcpu), vcpu->kvm))             \
 35                         return;                                            \
 36                 return td_vmcs_write##tdbits(to_tdx(vcpu), field, value);  \
 37         }                                                                  \
 38         vmcs_write##bits(field, value);                                    \
 39 }
```





