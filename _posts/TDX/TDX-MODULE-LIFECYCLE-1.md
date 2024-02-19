# Initialize TDX module
TDX module requires few initialization steps to start service as intermediary of
the TD and VMM. To this end, TDX module requires multiple SEAMCALLs to be 
invoked, as shown in the below figure, on multiple processors and packages. 
[[https://github.gatech.edu/sslab/tdx/blob/main/img/TDX_MODULE_INIT.png]]

All logical CPUs should be online during the TDX module initialization, which is 
implemented by the **__tdx_init** host kernel function. KVM is the only user of 
the TDX currently, so KVM always guarantees all online CPUs are in VMX operation
when there's any VM. 

### Host VMM talks to TDX module through SEAMCALL
Host VMM can only talks to the TDX Module through the SEAMCALL interface. The 
**init_tdx_module** function is the main host VMM function handling TDX Module 
initialization process. It invokes all required SEAMCALL from TDH_SYS_INIT to 
TDH_SYS_TDMR_INIT. Let's see how the KVM invokes the **init_tdx_module**. 

```cpp
static int __init vt_post_hardware_enable_setup(void)
{
        enable_tdx = enable_tdx && !tdx_module_setup();
        /*
         * Even if it failed to initialize TDX module, conventional VMX is
         * available.  Keep VMX usable.
         */
        return 0;
}
```


```cpp
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
int tdx_init(void)      
{       
        int ret;

        if (!platform_tdx_enabled())
                return -ENODEV;
        
        mutex_lock(&tdx_module_lock);
        
        switch (tdx_module_status) {
        case TDX_MODULE_UNKNOWN:
                ret = __tdx_init();
                break;
        case TDX_MODULE_NONE:
                ret = -ENODEV;
                break;
        case TDX_MODULE_INITIALIZED:
                ret = 0;
                break;
        default:
                WARN_ON_ONCE(tdx_module_status != TDX_MODULE_SHUTDOWN);
                ret = -EFAULT;
                break;
        }

        mutex_unlock(&tdx_module_lock);

        return ret;
}
```

```cpp
static int __tdx_init(void)
{
        int ret;

        /*
         * Initializing the TDX module requires running some code on
         * all MADT-enabled CPUs.  If not all MADT-enabled CPUs are
         * online, it's not possible to initialize the TDX module.
         *
         * For simplicity temporarily disable CPU hotplug to prevent
         * any CPU from going offline during the initialization.
         */     
        cpus_read_lock();
        
        /*
         * Check whether all MADT-enabled CPUs are online and return
         * early with an explicit message so the user can be aware.
         *
         * Note ACPI CPU hotplug is prevented when TDX is enabled, so
         * num_processors always reflects all present MADT-enabled
         * CPUs during boot when disabled_cpus is 0.
         */
        if (disabled_cpus || num_online_cpus() != num_processors) {
                pr_err("Unable to initialize the TDX module when there's offline CPU(s).\n");
                ret = -EINVAL;
                goto out;
        }
        
        ret = init_tdx_module();
        if (ret == -ENODEV) {
                pr_info("TDX module is not loaded.\n");
                goto out;
        }


```


```cpp
static int init_tdx_module(void)
{
        struct tdmr_info *tdmr_array;
        int tdmr_array_sz;
        int tdmr_num;
        int ret;

        ret = tdx_module_init_global();
        if (ret)
                goto out;

        if (trace_boot_seamcalls)
                tdx_trace_seamcalls(DEBUGCONFIG_TRACE_ALL);
        else
                tdx_trace_seamcalls(tdx_trace_level);

        ret = tdx_module_init_cpus();
        if (ret)
                goto out;

        ret = __tdx_get_sysinfo(&tdx_sysinfo, tdx_cmr_array, &tdx_cmr_num);
        if (ret)
                goto out;

        ret = check_memblock_tdx_convertible();
        if (ret)
                goto out;

        tdmr_array = alloc_tdmr_array(&tdmr_array_sz);
        if (!tdmr_array) {
                ret = -ENOMEM;
                goto out;
        }

        ret = construct_tdmrs_memeblock(tdmr_array, &tdmr_num);
        if (ret)
                goto out_free_tdmrs;

        tdx_global_keyid = tdx_keyid_start;

        ret = config_tdx_module(tdmr_array, tdmr_num, tdx_global_keyid);
        if (ret)
                goto out_free_pamts;

        wbinvd_on_all_cpus();

        ret = config_global_keyid();
        if (ret)
                goto out_free_pamts;

        ret = init_tdmrs(tdmr_array, tdmr_num);
        if (ret)
                goto out_free_pamts;

        tdx_module_status = TDX_MODULE_INITIALIZED;
        ......
}
```


## TDX Module Global Initialization (TDH_SYS_INIT SEAMCALL)
The host KVM cannot check whether the TDX module has been loaded or not because 
there is no MSR register indicating it. Instead of introducing another dedicated
MSR, TDX utilizes the SEAMCAL to check if the TDX module is loaded in the SEAMRR.
The first step of initializing the TDX module is module global initialization,
TDH_SYS_INIT. Therefore, by checking whether it fails with VMfailInvalid, KVM 
knows whether the TDX module has been successfully loaded. However, the primary
goal of the TDH_SYS_INIT SEAMCALL is to perform global initialization of the TDX
module. It includes checking processor state and initialize the global data for 
TDX module. 


### Generic TDX module initialization routine
**tdx_vmm_dispatcher** is the first function after saving some GPRs on the stack 
by the initial assembly code. If it is the first time that the current processor
enters the TDX Module, it first initialize three important variables for later 
TDX operations. Before dispatching the SEAMCALL leaf functions.

```cpp
127 // Must be first thing to do before accessing local/global data or sysinfo table
128 _STATIC_INLINE_ tdx_module_local_t* init_data_fast_ref_ptrs(void)
129 {
130     tdx_module_local_t* local_data = calculate_local_data();
131 
132     IF_RARE (!local_data->local_data_fast_ref_ptr)
133     {
134         local_data->local_data_fast_ref_ptr  = local_data;
135         local_data->sysinfo_fast_ref_ptr     = calculate_sysinfo_table();
136         local_data->global_data_fast_ref_ptr = calculate_global_data((sysinfo_table_t*)
137                                                     local_data->sysinfo_fast_ref_ptr);
138     }
139 
140     return local_data;
141 }
```

The TDX module excessively utilizes the per logical processor local_data. Also 
the local data points to two important data structure, sysinfo table and 
tdx_module_global.


```cpp
typedef struct PACKED tdx_module_local_s
{
    gprs_state_t          vmm_regs; /**< vmm host saved GPRs */
    gprs_state_t          td_regs;  /**< td guest saved GPRs */
    lp_info_t             lp_info;
    bool_t                lp_is_init;  /**< is lp initialized */
    ia32_debugctl_t       ia32_debugctl_value;

    vp_ctx_t              vp_ctx;

    stepping_t            single_step_def_state;

    non_extended_state_t  vmm_non_extended_state;
    keyhole_state_t       keyhole_state;

    void*                 local_data_fast_ref_ptr;
    void*                 global_data_fast_ref_ptr;
    void*                 sysinfo_fast_ref_ptr;

#ifdef DEBUGFEATURE_TDX_DBG_TRACE
    uint32_t              local_dbg_msg_num;
#endif

} tdx_module_local_t;
```

local_data is per processor and formatted following the tdx_module_local_t 
structure. Also, it resides in the local data memory region pointed to by the 
GSBASE. Through the local_data it can access the sysinfo and tdx_module_global 
data structure. Also note that it contains VMM regs.

```cpp
tdx_seamcall_entry_point:
    
    /**
     * Save all VMM GPRs on module entry to LP local data
     * Local data is located at GSBASE
     */
    movq %rax,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET
    movq %rcx,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+8
    movq %rdx,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+16
    movq %rbx,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+24
    movq %rsp,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+32 // not actually needed
    movq %rbp,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+40
    movq %rsi,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+48
    movq %rdi,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+56
    movq %r8,   %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+64
    movq %r9,   %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+72
    movq %r10,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+80
    movq %r11,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+88
    movq %r12,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+96
    movq %r13,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+104
    movq %r14,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+112
    movq %r15,  %gs:TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET+120
```

The VMM register state at the time of SEAMCALL invocation is stored inside the 
gs segment, which is the local_data.vmm_regs. Recall that P-SEAMLDR set the 
different memory region for GSBASE and stack for different VMCSs. Also, each
unique logical core utilize its owned VMCS, the local_data, located in the 
GSBASE. Therefore, multiple TDX module execution from different processors will 
not interfere other processor's local data. Physically, local_data of the first
processor is located in the data page of the TDX module, and the n(th) logical
core's GSBASE will be located back to back following the first local_data page.
The VMCS associated with the logical processor will be automatically selected 
by the SEAMCALL instruction.

After initializing local_data, some hardware features such as TSX and Branch 
History Buffer are initialized. Actually it is not initializing, but trying to 
close the side channels that possibly leak TDX module information. For example, 
it drains the BHB by executing multiple jump and call instructions. Also it has
some software based defense for specture variants.

### TDH_SYS_INIT on TDX module
The TDH_SYS_INIT SEAMCALL must be invoked only once during the lifetime of the 
target TDX module. It checks whether the MSR register has been correctly set
by comparing the information provided by the P-SEAMLDR such as sysinfo table. 
Also, because it is invoked only once, it initialize tdx_global_data_ptr. While
check_platform_config_and_cpu_enumeration function checks the MSR configuration,
it reads various MSR required for setting TDX module and save them in the global
data **plt_common_config**. For example, it reads MSR 0x87, IA32_MKTME_KEYID_
PARTITIONING and store the range of private HKID in the plt_common_config.



## Initializing ALL logical processors (TDH_SYS_LP_INIT SEAMCALL)
TDX requires all processors on the platform to invoke **TDH_SYS_LP_INIT**
SEAMCALL. It is a good place to initialize per processor data. For example, 
because the local data sections of each VMCS is continuously allocated with
fixed size, based on the address of the local data section of current VMCS, TDX
module can easily understand the lp_id of current processor.

```cpp
    tdx_local_data_ptr->lp_info.lp_id = (uint32_t)(((uint64_t) tdx_local_data_ptr
            - sysinfo_table->data_rgn_base) / LOCAL_DATA_SIZE_PER_LP);
```

### Initialize Keyhole
Also, it initialize keyhole state of each logical processor so that physical 
pages can be mapped to linear PTE through the keyhole. 

```cpp
#define MAX_KEYHOLE_PER_LP 128
typedef struct PACKED keyhole_state_s
{       
    /**     
     * Each index in the keyhole_array presents an offset of the mapped linear address.
     * The array also implement and LRU doubly linked-list.
     */ 
    keyhole_entry_t keyhole_array[MAX_KEYHOLE_PER_LP];
    /**     
     * A hash table, its index represents the index in the keyhole_array
     * that it is mapped to.
     */     
    uint16_t  hash_table[MAX_KEYHOLE_PER_LP];
    /**
     * lru_head and lru_tail present the index of the keyhole_array LRU
     * doubly linked-list.
     */
    uint16_t  lru_head;
    uint16_t  lru_tail;
    
#ifdef DEBUG
    /**
     * total_ref_count counts the total amount of non-statically mapped linear addresses.
     * Incremented on map_pa and decremented on free_la
     */
    uint64_t  total_ref_count;
#endif
} keyhole_state_t;
```

Each logical processor owns the keyhole_state_t which contains the 128 sized 
array for keyhole_entry_t. Also it has hash map to translate physical addresses
to an index of the keyhole_array. 

```cpp
typedef struct PACKED keyhole_entry_s
{   
    uint64_t  mapped_pa;  /**< mapped physical address of this keyhole entry */
    /** 
     * lru_next and lru_prev present an LRU doubly linked-list.
     */
    uint16_t  lru_next;
    uint16_t  lru_prev;
    uint16_t  hash_list_next;  /**< next element in hash list */
    /**
     * state can be KH_ENTRY_FREE or KH_ENTRY_MAPPED or KH_ENTRY_CAN_BE_REMOVED.
     */
    uint8_t   state;
    bool_t    is_writable;  /**< is PTE set to be Read-only or RW */
    bool_t    is_wb_memtype; /**< is PTE should be with WB or UC memtype */

    uint32_t ref_count; /** reference count of pages mapped in keyhole manager */
} keyhole_entry_t;
```
Each keyhole_entry_t structure holds physical to linear address mappings. Also,
it has a pointer to the next hash entry in the list. Because multiple different
physical addresses can be mapped to the same bucket, through the same 
keyhole_array index, it maintains all hash entries mapped to the same hash 
bucket as a linked lists by storing keyhole_array index of the next element.


## Get TDX module information (TDH_SYS_INFO SEAMCALL)
The return value of this SEAMCALL is TDSYSINFO_STRUCT and CMR_INFO table. 
Capabilities of TDX Module are enumerated in the returned TDSYSINFO_STRUCT. 
Also, CMRs, as previously set by BIOS and checked by MCHECK, are enumerated in 
the returned CMR_INFO table.

### TDSYSINFO_STRUCT 
It enumerates all information about the loaded TDX Module. 

```cpp
typedef struct PACKED td_sys_info_s
{
    /**
     * TDX Module Info
     */
    tdsysinfo_attributes_t attributes;
    uint32_t vendor_id; /**< 0x8086 for Intel */
    uint32_t build_date;
    uint16_t build_num;
    uint16_t minor_version;
    uint16_t major_version;
    uint8_t reserved_0[14]; /**< Must be 0 */

    /**
     * Memory Info
     */
    uint16_t max_tdmrs; /**< The maximum number of TDMRs supported. */
    uint16_t max_reserved_per_tdmr; /**< The maximum number of reserved areas per TDMR. */
    uint16_t pamt_entry_size; /**< The number of bytes that need to be reserved for the three PAMT areas. */
    uint8_t reserved_1[10]; /**< Must be 0 */

    /**
     * Control Struct Info
     */
    uint16_t tdcs_base_size; /**< Base value for the number of bytes required to hold TDCS. */
    uint8_t reserved_2[2]; /**< Must be 0 */
    uint16_t tdvps_base_size; /**< Base value for the number of bytes required to hold TDVPS. */
    /**
     * A value of 1 indicates that additional TDVPS bytes are required to hold extended state,
     * per the TD’s XFAM.
     * The host VMM can calculate the size using CPUID.0D.01.EBX.
     * A value of 0 indicates that TDVPS_BASE_SIZE already includes the maximum supported extended state.
     */
    bool_t tdvps_xfam_dependent_size;            
    uint8_t reserved_3[9]; /**< Must be 0 */

    /**
     * TD Capabilities
     */
    uint64_t attributes_fixed0; /**< If bit X is 0 in ATTRIBUTES_FIXED0, it must be 0 in any TD’s ATTRIBUTES. */
    uint64_t attributes_fixed1; /**< If bit X is 1 in ATTRIBUTES_FIXED1, it must be 1 in any TD’s ATTRIBUTES. */
    uint64_t xfam_fixed0; /**< If bit X is 0 in XFAM_FIXED0, it must be 0 in any TD’s XFAM. */
    uint64_t xfam_fixed1; /**< If bit X is 1 in XFAM_FIXED1, it must be 1 in any TD’s XFAM. */

    uint8_t reserved_4[32]; /**< Must be 0 */
    
    uint32_t num_cpuid_config; 
    cpuid_config_t cpuid_config_list[MAX_NUM_CPUID_CONFIG];
    uint8_t reserved_5[748];
} td_sys_info_t;
```

```cpp
    /**
     * Fill TDHSYSINFO_STRUCT
     */
    tdhsysinfo_output_la->attributes.raw = (uint32_t)0;
#ifdef DEBUG
    tdhsysinfo_output_la->attributes.debug_module = 1;
#endif
    tdhsysinfo_output_la->vendor_id = 0x8086;
    tdhsysinfo_output_la->build_date = TDX_MODULE_BUILD_DATE;
    tdhsysinfo_output_la->build_num = TDX_MODULE_BUILD_NUM;
    tdhsysinfo_output_la->minor_version = TDX_MODULE_MINOR_VER;
    tdhsysinfo_output_la->major_version = TDX_MODULE_MAJOR_VER;

    tdhsysinfo_output_la->max_tdmrs = MAX_TDMRS;
    tdhsysinfo_output_la->max_reserved_per_tdmr = MAX_RESERVED_AREAS; //MAX_RESERVED_PER_TDMR;
    tdhsysinfo_output_la->pamt_entry_size = sizeof(pamt_entry_t);

    tdhsysinfo_output_la->tdcs_base_size = _4KB * MAX_NUM_TDCS_PAGES; //_4KB * TDCS_PAGES;

    tdhsysinfo_output_la->tdvps_base_size = _4KB * MAX_TDVPS_PAGES; //_4KB * TDVPS_PAGES;

    tdhsysinfo_output_la->tdvps_xfam_dependent_size = false;

    tdhsysinfo_output_la->xfam_fixed0 = TDX_XFAM_FIXED0 &
                                       (uint64_t)(tdx_global_data_ptr->xcr0_supported_mask |
                                       tdx_global_data_ptr->ia32_xss_supported_mask);
    tdhsysinfo_output_la->xfam_fixed1 = TDX_XFAM_FIXED1;
    tdhsysinfo_output_la->attributes_fixed0 = tdx_global_data_ptr->attributes_fixed0;
    tdhsysinfo_output_la->attributes_fixed1 = tdx_global_data_ptr->attributes_fixed1;

    /**
     *  Write the first NUM_CONFIG CPUID_CONFIG entries These enumerate bits that are configurable by the host VMM.
     *  - CONFIG_DIRECT bits
     *  - ALLOW_DIRECT bits, if their native value is 1
     */

    tdhsysinfo_output_la->num_cpuid_config = MAX_NUM_CPUID_CONFIG;
    for (uint32_t i = 0; i < MAX_NUM_CPUID_CONFIG; i++)
    {
        tdhsysinfo_output_la->cpuid_config_list[i].leaf_subleaf =
                cpuid_lookup[i].leaf_subleaf;
        tdhsysinfo_output_la->cpuid_config_list[i].values.low = cpuid_configurable[i].config_direct.low |
                (cpuid_configurable[i].allow_direct.low &  tdx_global_data_ptr->cpuid_values[i].values.low);
        tdhsysinfo_output_la->cpuid_config_list[i].values.high = cpuid_configurable[i].config_direct.high |
                (cpuid_configurable[i].allow_direct.high & tdx_global_data_ptr->cpuid_values[i].values.high);
    }
```

### CMR_INFO
Convertible Memory Ranges (CMRs) are defined as physical address ranges that are
declared by BIOS, and checked by MCHECK, to hold only convertible memory pages. 
A 4KB memory page is defined as **convertible** if it can be used to hold an TDX
private memory page or any Intel TDX control structure pages. CMR_INFO provides 
base and size information of those CMRs to the host VMM.

```cpp
typedef struct PACKED cmr_info_entry_s
{
    /**
     * Base address of the CMR.  Since a CMR is aligned on 4KB, bits 11:0 are always 0.
     */
    uint64_t  cmr_base;
    /**         
     * Size of the CMR, in bytes.  Since a CMR is aligned on 4KB, bits 11:0 are always 0.
     * A value of 0 indicates a null entry.
     */
    uint64_t  cmr_size;
} cmr_info_entry_t; 
tdx_static_assert(sizeof(cmr_info_entry_t) == 16, cmr_info_entry_t);
```

```cpp
138     /**
139      * Fill CMR_INFO array
140      */
141     cmr_info_la_start = cmr_info_la;
142     for (uint8_t i = 0; i < MAX_CMR; i++)
143     {
144         *cmr_info_la = sysinfo_table_ptr->cmr_data[i];
145         cmr_info_la++;
146     };
```


### Why host needs those information? 
Q: If the TDX module already has the information, why the host kvm needs those information? 


### Map physical address belongs to the host kvm 
Although the required information will be all filled out by the TDX module, the
memory buffer belongs to the Host KVM side. Therefore, the passed physical addrs
should be mapped to the linear address by the TDX Module so that It can write 
content to the buffer. For that it utilize the keyhole. 

Each keyhole mapping holds physical to virtual address mapping. Because the 
memory space is limited for the TDX module, instead of utilizing full page table,
it partially pre-allocated the virtual address space. Keyhole is an indirection 
layer that maps physical address to virtual address residing in this reserved
region. To this end, physical address is hashed to generate the keyhole index 
used for retrieving the logical address it should be mapped to. With this 
indirection, we can utilize the limited but pre-assigned virtual address space
in memory scarce environment 

However, note that it must update the PTE, the leaf node of the page table, to 
actually map the physical address to the virtual address provided by a keyhole. 
Note that all non-leaf nodes required for pagetable walking is already populated
for the keyhole reserved virtual addresses. Therefore, only the leaf node needs 
to be populated at the end of the mapping process.


