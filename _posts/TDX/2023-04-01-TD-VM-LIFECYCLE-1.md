---
layout: post
title: "TD VM Life Cycle Part 1"
categories: [Confidential Computing, Intel TDX]
---

# Deep dive into TD-VM creation (TDH_MNG_CREATE SEAMCALL-TDH_MNG_INIT)
![TDX Init](/assets/img/TDX/TD_VM_INIT.png)

This article will follow the steps described in this figure. It is good to check
this figure when you want to check which part of the TD VM creation you are
dealing with. Before we delve into the details, lets first check new data 
structures required to generate and initialize the TD VM: **TDR, TDCS**. 

### Trust Domain Root (TDR)
>TDR is the root control structure of a guest TD. As designed, TDR is encrypted 
>using the Intel TDX global private HKID. It holds a minimal set of state 
>variables that enable guest TD control even during times when the TD’s private
>HKID is not known, or when the TD’s key management state does not permit access
>to memory encrypted using the TD’s private key. It is designed to be the first
>TD page to be allocated and the last to be removed. Its physical address serves
>as a ***unique identifier*** of the TD, as long as any TD page or control 
>structure resides in memory

The host VMM creates a new guest TD by TDH.MNG.CREATE SEAMCALL which initialize 
a TD Root(TDR) control structure. TDR is the memory page that can distinguish 
one TD VM from the others. Also, it is the most important page in TD VM creation 
because it is creating identity of TD VM instance. 


### Trust Domain Control Structure (TDCS)
[[https://github.gatech.edu/sslab/tdx/blob/main/img/TD_CONTROL_STRUCTURE.png]]
>TDCS is the main control structure of a guest TD. As designed, TDCS is 
>encrypted using the guest TD’s ephemeral private key. TDCS is a multi-page 
>logical structure composed of multiple TDCX physical pages. At a high level, 
>TDCS holds the following information:
>- EPTP: a pointer (HPA) to the TD’s **secure EPT root page** and EPT attributes.
>- Fields related to TD **measurement.**
>- MSR bitmaps: limiting capabilities of all TD’s VCPUs.
>- Fields controlling the TD operation as a whole (e.g., the number of VCPUs 
>  currently running).
>- Fields controlling the TD’s execution control (CPU features available to the 
>  TD, etc.).
>- A page filled with zeros: used in cases where the Intel TDX module needs a 
>  read-only constant-0 page encrypted with the TD’s private key.


Also, each TD VM requires the HKID to tag memory accesses and encrypt/decrypt 
private memory of the TD. Recall that the key should be within the private key 
range to not be exposed to the host VMM (refer to XXX)


## Create TD VM (KVM_CREATE_VM (QEMU) -> TDH_MNG_CREATE (TDX Module)
```cpp
static struct kvm_x86_ops vt_x86_ops __initdata = {
        ......
        .vm_init = vt_vm_init,
}

int kvm_arch_init_vm(struct kvm *kvm, unsigned long type)
{
        int ret;

        if (!static_call(kvm_x86_is_vm_type_supported)(type))
                return -EINVAL;
        ......
        return static_call(kvm_x86_vm_init)(kvm);
}
```

As part of the kvm_create_vm, the main function of creating all guest VM, the
kvm_arch_init_vm function is invoked to initiate generated KVM structure. This 
further invokes **vt_vm_init** assigned as vm_init operation of kvm_x86_ops.

```cpp
 123 static int vt_vm_init(struct kvm *kvm)
 124 {
 125         if (kvm->arch.vm_type == KVM_X86_TDX_VM)
 126                 return tdx_vm_init(kvm);
 127 
 128         return vmx_vm_init(kvm);
 129 }
```
Based on the VM type, whether it is TD VM or vanilla VM, it invokes different 
initialization functions. Before the TD VM initialization through SEAMCALL 
(KVM_TDX_INIT_VM), KVM needs to prepare TDR and TDCS structures to instantiate
and initialize the TD.

```cpp
static int tdx_vm_init(struct kvm *kvm)                                         
{             
        /* TODO: test 1GB support and remove tdp_max_page_level */
        kvm->arch.tdp_max_page_level = PG_LEVEL_2M;

        /* vCPUs can't be created until after KVM_TDX_INIT_VM. */
        kvm->max_vcpus = 0; 

        kvm_tdx->hkid = tdx_keyid_alloc();
        if (kvm_tdx->hkid < 0) 
                return -EBUSY;
       kvm_tdx->misc_cg = get_current_misc_cg();
       ret = misc_cg_try_charge(MISC_CG_RES_TDX, kvm_tdx->misc_cg, 1);
       if (ret)
               goto free_hkid;

        ret = tdx_alloc_td_page(&kvm_tdx->tdr);
        if (ret)
                goto free_hkid;

        kvm_tdx->tdcs = kcalloc(tdx_caps.tdcs_nr_pages, sizeof(*kvm_tdx->tdcs),
                                GFP_KERNEL_ACCOUNT);
        if (!kvm_tdx->tdcs)
                goto free_tdr;
        for (i = 0; i < tdx_caps.tdcs_nr_pages; i++) {
                ret = tdx_alloc_td_page(&kvm_tdx->tdcs[i]);
                if (ret)
                        goto free_tdcs;
        }    

```
KVM introduces the kvm_tdx structure to manage each TD instance. Although the
TDR and TDCS pages are filled out by the TDX Module, the physical pages used for
those two structures should be ready by the host KVM and passed to the TDX 
Module during the VM creation and initialization. 

```cpp
        mutex_lock(&tdx_lock);
        err = tdh_mng_create(kvm_tdx->tdr.pa, kvm_tdx->hkid);
        mutex_unlock(&tdx_lock);
        if (WARN_ON_ONCE(err)) {
                pr_tdx_error(TDH_MNG_CREATE, err, NULL);
                ret = -EIO;
                goto free_tdcs;
        }
        tdx_mark_td_page_added(&kvm_tdx->tdr);
```

After the physical page allocations, it invokes TDH_MNG_CREATE SEAMCALL with 
passing physical address of TDR page and the HKID as its input. 

### TDX Module side
Primary job of the TDX module for TDH_MNG_CREATE SEAMCALL is mapping the passed
TDR page as private and verifies that the passed key can be exclusively used for 
private memory of the TD VM. Let's see how it maps the physical page passed from
the VMM, which is not secure, to the private page of the TD VM. 

```cpp
api_error_type tdh_mng_create(uint64_t target_tdr_pa, hkid_api_input_t hkid_info)
{
    ......
    return_val = check_lock_and_map_explicit_tdr(tdr_pa,
                                                 OPERAND_ID_RCX,
                                                 TDX_RANGE_RW,
                                                 TDX_LOCK_EXCLUSIVE,
                                                 PT_NDA,
                                                 &tdr_pamt_block,
                                                 &tdr_pamt_entry_ptr,
                                                 &tdr_locked_flag,
                                                 &tdr_ptr);
    ......
}

api_error_type check_lock_and_map_explicit_tdr(
        pa_t tdr_hpa,
        uint64_t operand_id,
        mapping_type_t mapping_type,
        lock_type_t lock_type,
        page_type_t expected_pt,
        pamt_block_t* pamt_block,
        pamt_entry_t** pamt_entry,
        bool_t* is_locked,
        tdr_t** tdr_p
        )
{
    return check_lock_and_map_explicit_private_4k_hpa(tdr_hpa, operand_id, NULL, mapping_type,
            lock_type, expected_pt, pamt_block, pamt_entry, is_locked, (void**)tdr_p);
}   
```


```cpp
api_error_type check_lock_and_map_explicit_private_4k_hpa(
        pa_t hpa,
        uint64_t operand_id,
        tdr_t* tdr_p,
        mapping_type_t mapping_type,
        lock_type_t lock_type,
        page_type_t expected_pt,
        pamt_block_t* pamt_block,
        pamt_entry_t** pamt_entry,
        bool_t* is_locked,
        void**         la
        )
{       
    api_error_type errc;
    page_size_t leaf_size;
        
    errc = check_and_lock_explicit_4k_private_hpa( hpa, operand_id,
             lock_type, expected_pt, pamt_block, pamt_entry, &leaf_size, is_locked);
    if (errc != TDX_SUCCESS)
    {   
        return errc;
    }   
    
    pa_t hpa_with_hkid;
    
    errc = check_and_assign_hkid_to_hpa(tdr_p, hpa, &hpa_with_hkid);
    
    if (errc != TDX_SUCCESS)
    {
        TDX_ERROR("check_and_assign_hkid_to_hpa failure\n");
        *is_locked = false;
        pamt_unwalk(hpa, *pamt_block, *pamt_entry, lock_type, leaf_size);
        return api_error_with_operand_id(errc, operand_id);
    }


    *la = map_pa((void*)hpa_with_hkid.full_pa, mapping_type);

    return TDX_SUCCESS;
}
```
The main function for mapping TDR is check_lock_and_map_explicit_private_4k_hpa.
It consists of three parts, setting PAMT for the TDR page, assign HKID to the 
TDR hpa, and mapping the physical page. To map TDR hpa, TDX module utilizes the
global HKID of the TDX Module instead of the HKID of the target TD that owns TDR.
The key difference is the first part, setting PAMT. And the last part, mapping
physical page, we already covered [here.]

### Retrieving PAMT entry mapped to TDR 
```cpp
api_error_code_e non_shared_hpa_metadata_check_and_lock(
        pa_t hpa,
        lock_type_t lock_type,
        page_type_t expected_pt,
        pamt_block_t* pamt_block,
        pamt_entry_t** pamt_entry,
        page_size_t*   leaf_size,
        bool_t walk_to_leaf_size
        )
{
    // 1) Check that the operand’s HPA is within a TDMR (Trust Domain Memory Range) which is covered by a PAMT.
    if (!pamt_get_block(hpa, pamt_block))
    {
        TDX_ERROR("pamt_get_block error hpa = 0x%llx\n", hpa.raw);
        return TDX_OPERAND_ADDR_RANGE_ERROR;
    }

    page_size_t requested_leaf_size = *leaf_size;

    // 2) Find the PAMT entry for the page and verify that its metadata is as expected.
    pamt_entry_t* pamt_entry_lp = pamt_walk(hpa, *pamt_block, lock_type, leaf_size, walk_to_leaf_size);

    if (pamt_entry_lp == NULL)
    {
        TDX_ERROR("pamt_walk error\n");
        return TDX_OPERAND_BUSY;
    }

    if (walk_to_leaf_size && (requested_leaf_size != *leaf_size))
    {
        TDX_ERROR("PAMT entry level = %d , Expected level = %d\n", *leaf_size, requested_leaf_size);
        pamt_unwalk(hpa, *pamt_block, pamt_entry_lp, lock_type, *leaf_size);
        return TDX_PAGE_METADATA_INCORRECT;
    }

    if (pamt_entry_lp->pt != expected_pt)
    {
        TDX_ERROR("pamt_entry_lp->pt = %d , expected_pt = %d\n", pamt_entry_lp->pt, expected_pt);
        pamt_unwalk(hpa, *pamt_block, pamt_entry_lp, lock_type, *leaf_size);
        return TDX_PAGE_METADATA_INCORRECT;
    }

    *pamt_entry = pamt_entry_lp;

    return TDX_SUCCESS;
}
```

Regarding setting PAMT, it should first check the physical address of the TDR is
within one of the initialized TDMR. If the check passes, the base addresses of 
the three different levels of PAMT will be retrieved from the TDMR that covers 
the TDR PA. The next step is walking the PAMT table and retrieve the PAMT entry
mapped with the TDR PA. 

```cpp
pamt_entry_t* pamt_walk(pa_t pa, pamt_block_t pamt_block, lock_type_t leaf_lock_type,
                        page_size_t* leaf_size, bool_t walk_to_leaf_size)
{
    pamt_entry_t* pamt_1gb = map_pa_with_global_hkid(pamt_block.pamt_1gb_p, TDX_RANGE_RW);
    pamt_entry_t* pamt_2mb = map_pa_with_global_hkid(&pamt_block.pamt_2mb_p[pa.pamt_2m.idx], TDX_RANGE_RW);
    pamt_entry_t* pamt_4kb = map_pa_with_global_hkid(&pamt_block.pamt_4kb_p[pa.pamt_4k.idx], TDX_RANGE_RW);

    pamt_entry_t* ret_entry_pp = NULL;
    pamt_entry_t* ret_entry_lp = NULL;

    page_size_t target_size = walk_to_leaf_size ? *leaf_size : PT_4KB;

    // Acquire PAMT 1GB entry lock as shared
    if (acquire_sharex_lock_sh(&pamt_1gb->entry_lock) != LOCK_RET_SUCCESS)
    {
        goto EXIT;
    }

    // Return pamt_1g entry if it is currently a leaf entry
    if ((pamt_1gb->pt == PT_REG) || (target_size == PT_1GB))
    {
        // Promote PAMT lock to exclusive if needed
        if ((leaf_lock_type == TDX_LOCK_EXCLUSIVE) && !promote_sharex_lock(&pamt_1gb->entry_lock))
        {
            goto EXIT_FAILURE_RELEASE_ROOT;
        }

        *leaf_size = PT_1GB;
        ret_entry_pp = pamt_block.pamt_1gb_p;

        goto EXIT;
    }

    // Acquire PAMT 2MB entry lock as shared
    if (acquire_sharex_lock_sh(&pamt_2mb->entry_lock) != LOCK_RET_SUCCESS)
    {
        goto EXIT_FAILURE_RELEASE_ROOT;
    }

    // Return pamt_2m entry if it is leaf
    if ((pamt_2mb->pt == PT_REG) || (target_size == PT_2MB))
    {
        // Promote PAMT lock to exclusive if needed
        if ((leaf_lock_type == TDX_LOCK_EXCLUSIVE) && !promote_sharex_lock(&pamt_2mb->entry_lock))
        {
            goto EXIT_FAILURE_RELEASE_ALL;
        }

        *leaf_size = PT_2MB;
        ret_entry_pp = &pamt_block.pamt_2mb_p[pa.pamt_2m.idx];

        goto EXIT;
    }

    // Acquire PAMT 4KB entry lock as shared/exclusive based on the lock flag
    if (acquire_sharex_lock(&pamt_4kb->entry_lock, leaf_lock_type) != LOCK_RET_SUCCESS)
    {
        goto EXIT_FAILURE_RELEASE_ALL;
    }

    *leaf_size = PT_4KB;
    ret_entry_pp = &pamt_block.pamt_4kb_p[pa.pamt_4k.idx];

    goto EXIT;

EXIT_FAILURE_RELEASE_ALL:
    // Release PAMT 2MB shared lock
    release_sharex_lock_sh(&pamt_2mb->entry_lock);
EXIT_FAILURE_RELEASE_ROOT:
    // Release PAMT 1GB shared lock
    release_sharex_lock_sh(&pamt_1gb->entry_lock);

EXIT:
    free_la(pamt_1gb);
    free_la(pamt_2mb);
    free_la(pamt_4kb);

    if (ret_entry_pp != NULL)
    {
        ret_entry_lp = map_pa_with_global_hkid(ret_entry_pp,
                (leaf_lock_type == TDX_LOCK_EXCLUSIVE) ? TDX_RANGE_RW : TDX_RANGE_RO);
    }

    return ret_entry_lp;
}
```
Based on the target page size, different level of PATM will be returned. Because
the TDR page is a single 4KB page, it does need to walk the PAMT table three 
times (1GB, 2MB, 4KB) and then return the leaf node. After finding the PAMT 
entry, its virtual address is mapped and returned. 

### Rest of the TDH_MNG_CREATE on TDX Module
```cpp
pi_error_type tdh_mng_create(uint64_t target_tdr_pa, hkid_api_input_t hkid_info)
    ......
    // Mark the HKID entry in the KOT as assigned
    global_data->kot.entries[td_hkid].state = (uint8_t)KOT_STATE_HKID_ASSIGNED;

    // Set HKID in the TKT entry
    tdr_ptr->key_management_fields.hkid = td_hkid;
    tdr_ptr->management_fields.lifecycle_state = TD_HKID_ASSIGNED;

    // Set the new TDR page PAMT fields
    tdr_pamt_entry_ptr->pt = PT_TDR;
    tdr_pamt_entry_ptr->owner = 0;
```

Now the PAMT entry for the TDR is accessible, so it sets the PAMT for TDR (e.g.,
PT_TDR). Also, it checks whether the passed HKID is eligible for use of TD, for 
example, whether it belongs to the private HKID range. Also, it needs to check 
KOT to confirm that HKID can be exclusively used. If it is valid HKID, then the 
passed HKID is stored in the TDR.

## Program MKTME for TD (TDH_MNG_KEY_CONFIG)
To encrypt/decrypt the private pages of the TD, TDX Module should program the 
HKID and encryption key into the MKTME. Because MKTME exists per package, the 
TDH.MNG.KEY.CONFIG SEAMCALL should be invoked on each package. When the last 
package finished programming MKTME, the state of the TD is changed to 
UNINITIALIZED.

## Add TDCS Pages for TD (TDH_MNG_ADDCX)
After configuring the key, TDCX page should be added for the TD. Newly added
TDCX page is utilized for constructing TDCS. Recall that TDCS is a logical 
concept and consists of multiple physical TDCX pages. Also, when the TDCS pages
are mapped in the TDX module, it is accessible from the TDR of the specific VM.
It would be good to think of TDCS as a child of TDR. To add the TDCX pages, the
KVM host prepares physical page that can be mapped ad TDCX by the TDX Module. 
TDX module checks the validity of this physical page and maps with the **HKID 
assigned for the target TD**, not the global HKID of the TDX Module.

```cpp
        for (i = 0; i < tdx_caps.tdcs_nr_pages; i++) {
                err = tdh_mng_addcx(kvm_tdx->tdr.pa, kvm_tdx->tdcs[i].pa);
                if (WARN_ON_ONCE(err)) {
                        pr_tdx_error(TDH_MNG_ADDCX, err, NULL);
                        ret = -EIO;
                        goto teardown;
                }
                tdx_mark_td_page_added(&kvm_tdx->tdcs[i]);
        }
```

Also, the number of TDCX pages required for the TD is enumerated by the TDH.SYS.
INFO, which means multiple TDH_MNG_ADDCX SEAMCALL can be called to add TDCX 
pages. 



## Initialize TDCS (TDH_MNG_INIT)
Previously we added TDCX pages to the TD, but note that TDCX has logically 
meaningful usage, Trust Domain Control Structure. To utilize the TDCX pages as 
TDCS, it should be initialized, and the TDH_MNG_INIT SEAMCALL does this job. 
This initialization includes set an EPML4 page in one of the previously added 
TDCX pages as the root page of the secure EPT (TDCS.EPTP). 


### Host KVM passes TD_PARAMS to TDX Module 

```cpp
struct td_params {
        u64 attributes; 
        u64 xfam;
        u32 max_vcpus;
        u32 reserved0;
        
        u64 eptp_controls;
        u64 exec_controls;
        u16 tsc_frequency;
        u8  reserved1[38];
        
        u64 mrconfigid[6];
        u64 mrowner[6];
        u64 mrownerconfig[6];
        u64 reserved2[4];
                
        union {         
                struct tdx_cpuid_value cpuid_values[0];
                u8 reserved3[768];
        };      
} __packed __aligned(1024);
```

>TD_PARAMS is provided as an input to TDH.MNG.INIT, and some of its fields are 
>included in the TD report. The format of this structure is valid for a specific
>MAJOR_VERSION of the Intel TDX module, as reported by TDH.SYS.INFO

```cpp
static int tdx_td_init(struct kvm *kvm, struct kvm_tdx_cmd *cmd) {
        ......
        td_params = kzalloc(sizeof(struct td_params), GFP_KERNEL);
        if (!td_params) {
                ret = -ENOMEM;
                goto out;
        }

        ret = setup_tdparams(kvm, td_params, init_vm);
        if (ret)
                goto out;

        err = tdh_mng_init(kvm_tdx->tdr.pa, __pa(td_params), &out);
        if (WARN_ON_ONCE(err)) {
                pr_tdx_error(TDH_MNG_INIT, err, &out);
                ret = -EIO;
                goto out;
        }

        kvm_tdx->tsc_offset = td_tdcs_exec_read64(kvm_tdx, TD_TDCS_EXEC_TSC_OFFSET);
        kvm_tdx->attributes = td_params->attributes;
        kvm_tdx->xfam = td_params->xfam;
        kvm_tdx->tsc_khz = TDX_TSC_25MHZ_TO_KHZ(td_params->tsc_frequency);
	kvm->max_vcpus = td_params->max_vcpus;

        if (td_params->exec_controls & TDX_EXEC_CONTROL_MAX_GPAW)
                kvm->arch.gfn_shared_mask = gpa_to_gfn(BIT_ULL(51));
        else
                kvm->arch.gfn_shared_mask = gpa_to_gfn(BIT_ULL(47));
}
```

The main job of tdx_td_init function is invoking TDH.MNG.INIT SEAMCALL. For 
successful initialization of the TD VM, it requires TD_PARAMS which contains all
information such as measurement, tsc frequency, &c. Most of the information to 
build TD_PARAMS are provided by the QEMU. Let's take a look at how the TDX 
Module initializes the rest of the data structures. 

### Map TDCS pages for initialization 
To initializes the TDCS, the previously added TDCX pages should be accessible 
as the form of TDCS. Note that TDR maintains physical addresses of the TDCX.
map_implicit_tdcs function maps the TDCX pages and return the tdcs_t pointer. 
Note that it doesn't map the 4th page because it is used for PASID usage. 

```cpp
typedef struct ALIGN(TDX_PAGE_SIZE_IN_BYTES) tdcs_s
{   
    /**
     * TDCX First page - Management structures       
     */
    tdcs_management_fields_t               management_fields;
    tdcs_execution_control_fields_t        executions_ctl_fields;
    /**
     * Needs to be 128bit (16 byte) aligned for atomic cmpxchg
     */
    tdcs_epoch_tracking_fields_t ALIGN(16) epoch_tracking;
    tdcs_measurement_fields_t              measurement_fields;
    
    uint64_t                     notify_enables; // Enable guest notification of events
    
    /**
     * TDCX 2nd page - MSR Bitmaps
     */
    uint8_t ALIGN(TDX_PAGE_SIZE_IN_BYTES)                          MSR_BITMAPS[TDX_PAGE_SIZE_IN_BYTES]; /**< TD-scope RDMSR/WRMSR exit control bitmaps */
    
    /** 
     * TDCX 3rd page - Secure EPT Root Page
     */
    uint8_t ALIGN(TDX_PAGE_SIZE_IN_BYTES)                          sept_root_page[TDX_PAGE_SIZE_IN_BYTES];
    
    /**
     * TDCX 4th page - Zero Page
     */ 
    uint8_t ALIGN(TDX_PAGE_SIZE_IN_BYTES)                          zero_page[TDX_PAGE_SIZE_IN_BYTES];
} tdcs_t;
```

As shown in the above code, the TDCS consists of four TDCX pages and each field
is initialized during handling the TDH_MNG_INIT SEAMCALL.

### Initialize TDCS fields
```cpp
    /** 
     *  Read the TD configuration input and set TDCS fields
     */
    uint16_t virt_tsc_freq;

    return_val = read_and_set_td_configurations(tdcs_ptr,
                                                td_params_ptr,
                                                MAX_PA,
                                                tdr_ptr->management_fields.tdcx_pa[SEPT_ROOT_PAGE_INDEX],
                                                &virt_tsc_freq);

```

read_and_set_td_configurations configures most of the TDCS member fields, so 
it is hard to cover everything. Let's focus on some important TDCS member fields
such as **MSR bitmaps**, **TDCS measurement**, and **EPTP pointer** controlling
guest TD's GPA->HPA translation.

```cpp
    // Read and verify EPTP_CONTROLS
    target_eptp.raw = td_params_ptr->eptp_controls.raw;

    if ((target_eptp.fields.ept_ps_mt != MT_WB) ||
        (target_eptp.fields.ept_pwl < LVL_PML4) ||
        (target_eptp.fields.ept_pwl > LVL_PML5) ||
        (target_eptp.fields.enable_ad_bits != 0) ||
        (target_eptp.fields.enable_sss_control != 0) ||
        (target_eptp.fields.reserved_0 != 0) ||
        (target_eptp.fields.base_pa != 0) ||
        (target_eptp.fields.reserved_1 != 0))
    {
        return_val = api_error_with_operand_id(TDX_OPERAND_INVALID, OPERAND_ID_EPTP_CONTROLS);
        goto EXIT;
    }
    ,,,,,,
    /** 
     *  The PA field of EPTP points to the Secure EPT root page in TDCS,
     *  which has already been initialized to 0 during TDADDCX
     */
    target_eptp.fields.base_pa = sept_root_pa.page_4k_num;
    
    tdcs_ptr->executions_ctl_fields.eptp.raw = target_eptp.raw;
```
Based on the provided TD_PARAMS, it sets control bits of the EPTP first. After 
validating the control bits, it sets the EPTP root page table address, which is
the third TDCS page (tdcx_pa[SEPT_ROOT_PAGE_INDEX]). The populated EPTP info 
will be maintained in the first TDCS page, especially, executions_ctl_field.eptp.


## KVM_TDX_CAPABILITIES
Currently, KVM_TDX_CAPABILITIES is the only ioctl function supported through the
tdx device ioctl.

```cpp
int tdx_dev_ioctl(void __user *argp)
{
        struct kvm_tdx_capabilities __user *user_caps;
        struct kvm_tdx_capabilities caps;
        struct kvm_tdx_cmd cmd;

        BUILD_BUG_ON(sizeof(struct kvm_tdx_cpuid_config) !=
                     sizeof(struct tdx_cpuid_config));

        if (copy_from_user(&cmd, argp, sizeof(cmd)))
                return -EFAULT;
        if (cmd.flags || cmd.error || cmd.unused)
                return -EINVAL;
        /*
         * Currently only KVM_TDX_CAPABILITIES is defined for system-scoped
         * mem_enc_ioctl().
         */
        if (cmd.id != KVM_TDX_CAPABILITIES)
                return -EINVAL;

        user_caps = (void __user *)cmd.data;
        if (copy_from_user(&caps, user_caps, sizeof(caps)))
                return -EFAULT;

        if (caps.nr_cpuid_configs < tdx_caps.nr_cpuid_configs)
                return -E2BIG;

        caps = (struct kvm_tdx_capabilities) {
                .attrs_fixed0 = tdx_caps.attrs_fixed0,
                .attrs_fixed1 = tdx_caps.attrs_fixed1,
                .xfam_fixed0 = tdx_caps.xfam_fixed0,
                .xfam_fixed1 = tdx_caps.xfam_fixed1,
                .nr_cpuid_configs = tdx_caps.nr_cpuid_configs,
                .padding = 0,
        };

        if (copy_to_user(user_caps, &caps, sizeof(caps)))
                return -EFAULT;
        if (copy_to_user(user_caps->cpuid_configs, &tdx_caps.cpuid_configs,
                         tdx_caps.nr_cpuid_configs *
                         sizeof(struct tdx_cpuid_config)))
                return -EFAULT;

        return 0;
}

```

### KVM retrieve and store TDX capabilities information 
To return the proper information about TDX, KVM module should have invoked 
TDCALL to tdx module and memorize all required information beforehand. 

```cpp
/* Capabilities of KVM + the TDX module. */
static struct tdx_capabilities tdx_caps;

int __init tdx_module_setup(void)
{
        const struct tdsysinfo_struct *tdsysinfo;
        int ret = 0;

        BUILD_BUG_ON(sizeof(*tdsysinfo) != 1024);
        BUILD_BUG_ON(TDX_MAX_NR_CPUID_CONFIGS != 37);

        ret = tdx_init();
        if (ret) {
                pr_info("Failed to initialize TDX module.\n");
                return ret;
        }

        tdx_global_keyid = tdx_get_global_keyid();

        tdsysinfo = tdx_get_sysinfo();
        if (tdsysinfo->num_cpuid_config > TDX_MAX_NR_CPUID_CONFIGS)
                return -EIO;

        tdx_caps = (struct tdx_capabilities) {
                .tdcs_nr_pages = tdsysinfo->tdcs_base_size / PAGE_SIZE,
                /*
                 * TDVPS = TDVPR(4K page) + TDVPX(multiple 4K pages).
                 * -1 for TDVPR.
                 */
                .tdvpx_nr_pages = tdsysinfo->tdvps_base_size / PAGE_SIZE - 1,
                .attrs_fixed0 = tdsysinfo->attributes_fixed0,
                .attrs_fixed1 = tdsysinfo->attributes_fixed1,
                .xfam_fixed0 =  tdsysinfo->xfam_fixed0,
                .xfam_fixed1 = tdsysinfo->xfam_fixed1,
                .nr_cpuid_configs = tdsysinfo->num_cpuid_config,
        };
        if (!memcpy(tdx_caps.cpuid_configs, tdsysinfo->cpuid_configs,
                        tdsysinfo->num_cpuid_config *
                        sizeof(struct tdx_cpuid_config)))
                return -EIO;

        return 0;
}
```


```cpp
struct tdx_capabilities {
        u8 tdcs_nr_pages;
        u8 tdvpx_nr_pages;

        u64 attrs_fixed0;
        u64 attrs_fixed1;
        u64 xfam_fixed0;
        u64 xfam_fixed1;

        u32 nr_cpuid_configs;
        struct tdx_cpuid_config cpuid_configs[TDX_MAX_NR_CPUID_CONFIGS];
};

```

**tdx_capabilities** struct selectively contains the information provided through tdsysinfo.
tdsysinfo can be retrieved from the TDX module through the tdcall as shown in the below. 
Host KVM retrieves the tdsysinfo as a result of TDH_SYS_INFO SEAMCALL at the time 
of init_tdx_module.


