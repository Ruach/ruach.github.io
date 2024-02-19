## Init orders
Linux defines below order of inits
```cpp
#define early_initcall(fn)		module_init(fn)
#define core_initcall(fn)		module_init(fn)
#define postcore_initcall(fn)		module_init(fn)
#define arch_initcall(fn)		module_init(fn)
#define subsys_initcall(fn)		module_init(fn)
#define fs_initcall(fn)			module_init(fn)
#define rootfs_initcall(fn)		module_init(fn)
#define device_initcall(fn)		module_init(fn)
#define late_initcall(fn)		module_init(fn)
```

TDX module installs three initcall defined as below

```cpp
early_initcall(tdx_host_early_init);
arch_initcall(tdx_arch_init);
subsys_initcall_sync(tdx_late_init);  
```

## Early init of TDX module 
In this module initialization, we can think of three major role. The first one 
is checking if CPU features required to run TDX presents on this hardware 
platforms. The second one is getting p_seamldr information through seamcall. The
last one is initializing TDX system memory. I will skip the CPU configuration 
check. 

### Getting p_seamldr information 
Important semantic here is CPU needs to run as VMX root when it invokes seamcall.
```cpp
421         /* P-SEAMLDR executes in SEAM VMX-root that requires VMXON. */
422         vmcs = (struct vmcs *)get_zeroed_page(GFP_KERNEL);
423         if (!vmcs) {
424                 err = -ENOMEM;
425                 goto out;
426         }
427         seam_init_vmxon_vmcs(vmcs);
428 
429         /* Because it's before kvm_init, VMX shouldn't be enabled. */
430         WARN_ON(__read_cr4() & X86_CR4_VMXE);
431         err = cpu_vmxon(__pa(vmcs));
432         if (err)
433                 goto out;
434 
435         err = seamldr_info(__pa(p_seamldr_info));
436 
437         /*
438          * Other initialization codes expect that no one else uses VMX and that
439          * VMX is off.  Disable VMX to keep such assumptions.
440          */
441         vmxoff_err = cpu_vmxoff();
```

```cpp
 60 int seamldr_info(phys_addr_t seamldr_info)
 61 {
 62         u64 ret;
 63 
 64         ret = pseamldr_seamcall(SEAMCALL_SEAMLDR_INFO, seamldr_info, 0,
 65                                 0, 0, NULL);
```

### Initializing TDX system memory 

```cpp
 79 static int __init __tdx_sysmem_build(void)
 80 {
 81         unsigned long start_pfn, end_pfn;
 82         int i, nid, ret;
 83 
 84         pr_info("Build all system memory blocks as TDX memory.\n");
 85 
 86         tdx_memory_init(&tmem_sysmem);
 87 
 88         for_each_mem_pfn_range(i, MAX_NUMNODES, &start_pfn, &end_pfn, &nid) {
 89                 ret = tdx_sysmem_add_block(&tmem_sysmem, start_pfn, end_pfn,
 90                                 nid);
 91                 if (ret)
 92                         goto err;
 93         }
 94 
 95         return 0;
 96 err:
 97         pr_err("Fail to build system memory as TDX memory.\n");
 98         tdx_sysmem_cleanup();
 99         return ret;
100 }
```

Note that tmem_sysmem contains system memory blocks that can be used as TDX 
memory blocks.Another memory region that can be used for TDX memory block is 
legacy TMEM.


```cpp
 42 static int __init tdx_sysmem_add_block(struct tdx_memory *tmem,
 43                 unsigned long start_pfn, unsigned long end_pfn, int nid)
 44 {
 45         struct tdx_memblock *tmb;
 46         int ret;
 47 
 48         /*
 49          * Before constructing TDMRs to convert convertible memory as TDX
 50          * memory, kernel checks whether all TDX memory blocks are fully
 51          * covered by BIOS provided convertible memory regions (CMRs),
 52          * and refuses to convert if any is not.
 53          *
 54          * The BIOS generated CMRs won't contain memory below 1MB.  To avoid
 55          * above check failure, explicitly skip memory below 1MB as TDX
 56          * memory block.  This is fine since memory below 1MB is already
 57          * reserved in setup_arch(), and won't be managed by page allocator
 58          * anyway.
 59          */
 60         if (start_pfn < (SZ_1M >> PAGE_SHIFT))
 61                 start_pfn = (SZ_1M >> PAGE_SHIFT);
 62 
 63         if (start_pfn >= end_pfn)
 64                 return 0;
 65 
 66         tmb = tdx_memblock_create(start_pfn, end_pfn, nid, NULL, &sysmem_ops);
 67         if (!tmb)
 68                 return -ENOMEM;
 69 
 70         ret = tdx_memory_add_block(tmem, tmb);
 71         if (ret) {
 72                 tdx_memblock_free(tmb);
 73                 return ret;
 74         }
 75 
 76         return 0;
 77 }

```

TDX block indicates which physical memory region can be used as TDX memory in 
the future.

## Loading TDX module 
### TDH.SYS.CONFIG: Global TDX configurations from VMM
[[https://github.gatech.edu/sslab/tdx/blob/main/img/TDH.SYS.CONFIG-params.png]]

tdx_load_module: TDX module binary and sigstruct location should be passed to 
kernel at compile time. This function just load XXX.
The number of page required to load TDX module is measured based on the TDX 
module size. **seamldr_params** structure is used to pass TDX module information
to TDX.

tdx_install_module_cpu: This function should be called on all processors to load 
TDX module. 

seamldr_install (Kernel side function): This function will invoke the **fisrt** 
seamcall to load TDX module(SEAMCALL_SEAMLDR_INSTALL). But note that it is 
**p-seamldr SEAMCALL** not just SEAMCALL to TDX module. Therefore, it will 
invoke dispatcher function residing inside seam loader. It will end up invoking 
seamldr_install function.

seamldr_install (TDX loader side function): Note that it is the function of the 
p-seamldr,not the TDX module function. It will load the TDX module so current 
scope is p-seamldr. It checkcks the seamldr_params and Sigstruct before loading
the TDX module. Also memory required for loading TDX module is calculated 
(initialize_memory_constraints) and mapped to seam loader address space by 
seam_module_memory_map (?). Finally, the function seam_module_load_and_verify is 
invoked and the TDX module is loaded. It also measures the has value of the TDX 
module and reject loading when the hash does not match with the pre-calculated 
value stored in the sigstruct for TDX module. One of its important role is 
setting the VMCS structure associated with seam loader (refer to setup_seam_vmcs).

[[https://github.gatech.edu/sslab/tdx/blob/main/img/SEAMCALL_ENTER.png]]
### Same seamcall but different entry points (TDX module and TDX loader):
Basically, the MSB of the rax register determines where the seamcall exit to 
(1 for P-seamldr, 0 for TDX module). Also, the transition from the VMX Root to 
SEAM VMX Root is presented as an VM exit. Following the original semantic of VMX
Root operation, when the VM exit happens it should jump to the predetermined 
code location specified in the VMCS. TDX cannot believe the VMM layer so 
seamcall operation switches the VMCS automatically (in micro-architecture) and 
jump to the pre-programmed locations. This location is fixed by specification of
the TDX: if it invokes p-seamldr, it will locate the VMCS associated with the 
P-Seamldr. This VMCS can be configured by the NP-Seamldr and can be located by 
the seamcall instruction. Also, for the TDX module, the location of the VMCS 
structure is determined based on which logical processor the seamcall 
instruction is invoked on. 

```c
VMCS_FOR_TDX = IA32_SEAMRR_PHYS_BASE + 4096 + CPUID.B.0.EDX [31:0] * 4096.
```

### Initialization of VMCS for TDX module (**by pseamldr**)
The VMCS structure for TDX module is configured by the P-Seamldr while it loads 
the TDX module by setup_seam_vmcs function. The most important field of the VMCS
associated with TDX module is **host rip, gs and fs base**. host rip indicates
where it jumps to when seamcall is invoked by the kernel-side (for TDX module). 
Also, **gsbase is used as a local storage for each logical processor** inside 
the TDX module. Lastly, the fs base contains the sysinfo_table.

Let's see how pseamldr sets gsbase of the TDX module. pseamldr first needs to 
understand the memory layout of the TDX module that will be loaded into the 
SEAMRR.base. 

```cpp
322     // Data region:
323     mem_consts->local_data_size = (seam_sigstruct->num_tls_pages + 1) * _4KB;
324     mem_consts->global_data_size = (seam_sigstruct->num_global_data_pages + 1) * _4KB;
325     mem_consts->data_region_size = (mem_consts->local_data_size * mem_consts->num_addressable_lps) +
326                                     mem_consts->global_data_size;
327     mem_consts->data_region_linbase = LINEAR_BASE_DATA_REGION | aslr_mask;
328     mem_consts->data_region_physbase = pseamldr_data->system_info.seamrr_base +
329                                        _4KB + mem_consts->vmcs_region_size; // Physical SYSINFO table and VMCS's
```

pseamldr sets the data region of the tdx module based on the tdx module info, 
and this data_region will be used for fsbase.

```cpp
 70     wr_host_rip(vmcs_la_base, mem_consts->code_region_linbase + rip_offset);
 71     wr_host_fs_base(vmcs_la_base, mem_consts->sysinfo_table_linbase);
 72
 73     uint64_t host_rsp_first_lp = mem_consts->stack_region_linbase + mem_consts->data_stack_size - 8;
 74     uint64_t host_ssp_first_lp = mem_consts->stack_region_linbase + mem_consts->lp_stack_size - 8;
 75     uint64_t host_gsbase_first_lp = mem_consts->data_region_linbase;
 76 
 77     wr_host_rsp(vmcs_la_base, host_rsp_first_lp);
 78     wr_host_ssp(vmcs_la_base, host_ssp_first_lp);
 79     wr_host_gs_base(vmcs_la_base, host_gsbase_first_lp);
 80     wr_vmcs_revision_id(vmcs_la_base, vmx_basic.vmcs_revision_id);
 81 
 82     uint64_t vmcs_size = vmx_basic.vmcs_region_size;
 83 
 84     for (uint64_t i = 1; i < mem_consts->num_addressable_lps; i++)
 85     {
 86         uint64_t current_vmcs_la = vmcs_la_base + (i * PAGE_SIZE_IN_BYTES);
 87         pseamldr_memcpy((void*)current_vmcs_la, vmcs_size, (void*)vmcs_la_base, vmcs_size);
 88         wr_host_rsp(current_vmcs_la, host_rsp_first_lp + (i * mem_consts->lp_stack_size));
 89         wr_host_ssp(current_vmcs_la, host_ssp_first_lp + (i * mem_consts->lp_stack_size));
 90         wr_host_gs_base(current_vmcs_la, host_gsbase_first_lp + (i* mem_consts->local_data_size));
 91     }
```

Based on the number of available logical processor (num_addressable_lps), 
pseamldr sets the host gs base address, which is used by the tdx module when the
seamcall is invoked by the VMM (vmexit). Note that each processor has unique 
VMCS and data sections.

### How does the seam loader maps the physical address to linear address? 
Note that some variables are linear address not physical. The mapping will be 
generated by seam_module_memory_map function. For example, fs_base is set as 
mem_consts->sysinfo_table_linbase which will be mapped to physical address of 
the sysinfo_table for the TDX module. In detail, map_regular_range function is
used for generating pa to la map.

As shown in the below code, mem_consts->sysinfo_table_linbase is mapped to 
physical address pseamldr_data->system_info.semarr_base which is the actual 
physical page containing the sysinfo_table of the tdx module. 

```cpp
187     // Sysinfo page
188     if (!map_regular_range(mem_consts, pseamldr_data->system_info.seamrr_base, mem_consts->sysinfo_table_linbase,
189                            _4KB, SEAM_SYSINFO_RANGE_ATTRIBUTES))
190     {
191         TDX_ERROR("Sysinfo table mapping failure\n");
192         return PSEAMLDR_ENOMEM;
193     }
```


```cpp
 86 static bool_t map_regular_range(memory_constants_t* mem_consts, uint64_t range_pa, uint64_t range_la,
 87                                 uint64_t size_in_bytes, uint64_t attributes)
 88 {
 89     for (uint64_t i = 0; i < size_in_bytes / PAGE_SIZE_IN_BYTES; i++)
 90     {
 91         uint64_t pxe_pa = map_seam_range_page(mem_consts, range_pa, range_la, attributes, false);
 92         IF_RARE (pxe_pa == NULL_PA)
 93         {
 94             return false;
 95         }
 96         range_pa += PAGE_SIZE_IN_BYTES;
 97         range_la += PAGE_SIZE_IN_BYTES;
 98     }
 99 
100     return true;
101 }
```


```cpp
 27 static uint64_t map_seam_range_page(memory_constants_t* mem_consts, uint64_t pa, uint64_t la, uint64_t attributes,
 28                                     bool_t keyhole_range)
 29 {
 30     uint64_t pt_idx;
 31     ia32e_pxe_t* pxe_ptr;
 32     uint64_t pxe_pa;
 33 
 34     uint64_t seamrr_linear_delta = get_psysinfo_table()->module_region_base - get_pseamldr_data()->system_info.seamrr_base;
 35 
 36     pxe_pa = mem_consts->pml4_physbase;
 37 
 38     // walk and fill if needed non leaf levels
 39     for (uint64_t i = SEAM_MODULE_PAGE_LEVEL - 1; i > 0; i--)
 40     {
 41         pxe_ptr = (ia32e_pxe_t*)(pxe_pa + seamrr_linear_delta);
 42         pt_idx = (la >> (i * 9 + 12)) & 0x1FF;
 43         // check if PT exists
 44         if (pxe_ptr[pt_idx].raw == 0)
 45         {
 46             // if the allocator got to the data region - we are out of memory
 47             // SEAM range physical map: (bigger address at the bottom)
 48             // ==========================
 49             // SEAMRR_BASE
 50             // SEAM VMCS area
 51             // Data region (address grows up)
 52             // SEAM page table region end (last page table available) and Data region end
 53             // SEAM page table region start - current_pt_physbase (address grows down)
 54             // SEAM PML4 page table
 55             // Stack region
 56             uint64_t data_region_end = mem_consts->data_region_physbase + mem_consts->data_region_size;
 57             if (mem_consts->current_pt_physbase <= data_region_end)
 58             {
 59                 return NULL_PA;
 60             }
 61             pxe_ptr[pt_idx].raw = mem_consts->current_pt_physbase;
 62 
 63             if (keyhole_range && (i == PAGING_LEVEL_PDE))
 64             {
 65                 pxe_ptr[pt_idx].raw |= SEAM_KEYHOLE_PDE_ATTRIBUTES;
 66             }
 67             else
 68             {
 69                 pxe_ptr[pt_idx].raw |= SEAM_NON_LEAF_PXE_ATTRIBUTES;
 70             }
 71 
 72             mem_consts->current_pt_physbase -= PAGE_SIZE_IN_BYTES;
 73         }
 74 
 75         pxe_pa = (uint64_t)(pxe_ptr[pt_idx].fields_4k.addr) << IA32E_4K_PAGE_OFFSET;
 76     }
 77     // map leaf level
 78     pt_idx = ((pa_t)la).fields_4k.pt_index;
 79 
 80     pxe_ptr = (ia32e_pxe_t*)(pxe_pa + seamrr_linear_delta);
 81     pxe_ptr[pt_idx].raw = pa | attributes;
 82 
 83     return pxe_pa;
 84 }
```


XXX: Who assigns when the sysinfo_table to the seamrr register... 
I mean who assign the sys_info to physical memory?

### Configure TDMR and PAMT 
[[https://github.gatech.edu/sslab/tdx/blob/main/img/TDMR_INFO.png]]

### Configure HKEY for TDX module (encrypting TDMR and PAMT)


## Initialize TDX module &c. 
[[https://github.gatech.edu/sslab/tdx/blob/main/img/TDX_MODULE_INIT.png]]

### Kernel side invocations
After loading the TDX module,host kernel invokes tdx_init_system function for system wide
initialization of TDX module. 

tdx_init_system (kernel side): Invoke RDMSR to retrieve HKID information for TDX module. 
The values of NUM_MKID_KEYS (number of shared keys) and NUM_TDX_PRIV_KEYS (number of 
private keys for TD VM) are read from the IA32_MKTME_KEYID_PARTITIONING MSR (0x87). Note
that HKID 0 is reserved for legacy TME, so HKID should start from 1. After that, it invokes 
another SEAMCALL (TDH.SYS.INIT). Note that this functions is the first seamcall to TDX 
module. Seamcall invokes vmexit to the TDX module and switches the processor context 
following the VMCS structure which is set by the pseamldr. Therefore, it jumps to the 
MODULE_ENTRY_POINT, which is the tdx_seamcall_entry_point. It first pushes the GPRs to 
the gs segment and clear the registers before executing the first function of the TDX 
module, tdx_vmm_dispatcher.

### TDX module side seamcall handling
tdx_vmm_dispatcher (TDX module): TDX module excessively utilizes the local_data stored in 
the gs segment, which is associated with the unique logical processor. The local_data is 
just a pointer to tdx_module_local_t structure located in the gs segment. Below code shows
the structure tdx_module_local_t and how to locate the structure from the gs segment of the
logical processor. 

```cpp
221 typedef struct PACKED tdx_module_local_s
222 {
223     gprs_state_t          vmm_regs; /**< vmm host saved GPRs */
224     gprs_state_t          td_regs;  /**< td guest saved GPRs */
225     lp_info_t             lp_info;
226     bool_t                lp_is_init;  /**< is lp initialized */
227     ia32_debugctl_t       ia32_debugctl_value;
228 
229     vp_ctx_t              vp_ctx;
230 
231     stepping_t            single_step_def_state;
232 
233     non_extended_state_t  vmm_non_extended_state;
234     keyhole_state_t       keyhole_state;
235 
236     void*                 local_data_fast_ref_ptr;
237     void*                 global_data_fast_ref_ptr;
238     void*                 sysinfo_fast_ref_ptr;
239 
240 #ifdef DEBUGFEATURE_TDX_DBG_TRACE
241     uint32_t              local_dbg_msg_num;
242 #endif
243 
244 } tdx_module_local_t;
245 tdx_static_assert(offsetof(tdx_module_local_t, vmm_regs) == TDX_LOCAL_DATA_VMM_GPRS_STATE_OFFSET, tdx_module_local_t);
246 tdx_static_assert(offsetof(tdx_module_local_t, td_regs) == TDX_LOCAL_DATA_TD_GPRS_STATE_OFFSET, tdx_module_local_t);
```

```cpp
 83 // In SEAM TDX module, GSBASE holds a pointer to the local data of current thread
 84 // We are reading GSBASE by loading effective address of 0 with GS prefix
 85 _STATIC_INLINE_ tdx_module_local_t* calculate_local_data(void)
 86 {
 87     void* local_data_addr;
 88     _ASM_VOLATILE_ ("rdgsbase %0"
 89                     :"=r"(local_data_addr)
 90                     :
 91                     :"cc");
 92 
 93     return (tdx_module_local_t*)local_data_addr;
 94 }
```

If the current processor enters the TDX module first time, it assigns some pointer members 
of the tdx_module_local_t so that it can accesses different data structures through it.

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

Also, remind that sysinfo_table is passed to the TDX module by the pseamldr through 
the fs segment. Refer to below code.

```cpp
 96 // In SEAM TDX module, FSBASE holds a pointer to the SYSINFO table
 97 // We are reading FSBASE by loading effective address of 0 with FS prefix
 98 _STATIC_INLINE_ sysinfo_table_t* calculate_sysinfo_table(void)
 99 {
100     void* sysinfo_table_addr;
101     _ASM_VOLATILE_ ("rdfsbase %0"
102                     :"=r"(sysinfo_table_addr)
103                     :
104                     :"cc");
105 
106     return (sysinfo_table_t*)sysinfo_table_addr;
107 }
```

XXX: I don't know what is global data here (tdx_module_global_t?)

After initializing local_data, some hardware features such as TSX and Branch History Buffer
are initialized. Actually it is not initializing, but trying to close the side channels that
can possibly leak TDX module information. For example, it drains the BHB by executing multiple
jump and call instructions. Also it has some software based defense for specture variants (out 
of my scope). And then some other initialization continue.. 

tdh_sys_init: Mostly it checks whether the MSR register has been correctly set based on the 
information provided by the pseamldr. GS segment of each logical processor contains data
that can be interpreted with **tdx_module_local_t**, which is the local data of the current 
thread. Also, note that gsbase address of the first logical processor has been set as the 
first data page of TDX module, and the n(th) logical core's gsbase follows the first data 
page. 


## Initializing ALL logical processors
TDX requires all processors on the platform to be initialized by the TDX module. For that,
it invokes **TDH_SYS_LP_INIT** seamcall on every logical processor (invoking tdx_init_cpus
on TDX module side).

## Get TDX module information 
```cpp
783         err = tdh_sys_info(__pa(tdx_tdsysinfo), sizeof(*tdx_tdsysinfo)
784                            __pa(tdx_cmrs), TDX_MAX_NR_CMRS, &ex_ret);
```

```cpp
 28 api_error_type tdh_sys_info(uint64_t tdhsysinfo_output_pa,
 29                 uint64_t num_of_bytes_in_buffer, uint64_t target_cmr_info_pa,
 30                 uint64_t num_of_cmr_info_entries)
 31 {
 32     api_error_type retval = TDX_OPERAND_INVALID;
 33     pa_t tdhsysinfo_pa = {.raw = tdhsysinfo_output_pa};
 34     pa_t cmr_info_pa = {.raw = target_cmr_info_pa};
 35     td_sys_info_t * tdhsysinfo_output_la = 0;
 36     cmr_info_entry_t* cmr_info_la = 0;
 37     cmr_info_entry_t* cmr_info_la_start = 0;
 38     tdx_module_global_t * tdx_global_data_ptr = get_global_data();
 39     tdx_module_local_t * tdx_local_data_ptr = get_local_data();
 40     sysinfo_table_t * sysinfo_table_ptr = get_sysinfo_table();
```

Because physical addresses are passed to the TDX module, it should be mapped to logical 
address of the TDX module. Also, this address is shared address not private, which can be
directly read/written by the TDX module. 

```cpp
 98     tdhsysinfo_output_la->vendor_id = 0x8086;
 99     tdhsysinfo_output_la->build_date = TDX_MODULE_BUILD_DATE;
100     tdhsysinfo_output_la->build_num = TDX_MODULE_BUILD_NUM;
101     tdhsysinfo_output_la->minor_version = TDX_MODULE_MINOR_VER;
102     tdhsysinfo_output_la->major_version = TDX_MODULE_MAJOR_VER;
103 
104     tdhsysinfo_output_la->max_tdmrs = MAX_TDMRS;
105     tdhsysinfo_output_la->max_reserved_per_tdmr = MAX_RESERVED_AREAS; //MAX_RESERVED_PER_TDMR;
106     tdhsysinfo_output_la->pamt_entry_size = sizeof(pamt_entry_t);
107 
108     tdhsysinfo_output_la->tdcs_base_size = _4KB * MAX_NUM_TDCS_PAGES; //_4KB * TDCS_PAGES;
109 
110     tdhsysinfo_output_la->tdvps_base_size = _4KB * MAX_TDVPS_PAGES; //_4KB * TDVPS_PAGES;
111 
112     tdhsysinfo_output_la->tdvps_xfam_dependent_size = false;
113 
114     tdhsysinfo_output_la->xfam_fixed0 = TDX_XFAM_FIXED0 &
115                                        (uint64_t)(tdx_global_data_ptr->xcr0_supported_mask |
116                                        tdx_global_data_ptr->ia32_xss_supported_mask);
117     tdhsysinfo_output_la->xfam_fixed1 = TDX_XFAM_FIXED1;
118     tdhsysinfo_output_la->attributes_fixed0 = tdx_global_data_ptr->attributes_fixed0;
119     tdhsysinfo_output_la->attributes_fixed1 = tdx_global_data_ptr->attributes_fixed1;
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

## TDX kernel module late init 
During the architecture init, it loaded the tdx module and finished initialization.
After that, tdx_late_init function will be called later to finish further init process
such as setting TDMR.

```cpp
1403 /*
1404  * subsys_initcall_sync() is chosen to satisfy the following conditions.
1405  * - After P-SEAMLDR is loaded.
1406  * - After the TDX module is loaded.
1407  * - After iomem_resouce is populated with System RAM including regions
1408  *   specified by memmap=nn[KMG]!ss[KMG], which is done by
1409  *   e820_reserve_resources() called by setup_arch().  Because
1410  *   tdx_construct_tdmr() walks iomem resources looking for legacy pmem region.
1411  * - After build_sysmem_tdx_memory() by early_initcall().
1412  * - After reserved memory region is polulated in iomem_resource by
1413  *   e820__reserve_resources_late(), which is called by
1414  *   subsys_initcall(pci_subsys_init).
1415  * - After numa node is initialized by pgdata_init() and alloc_contig_pages() is
1416  *   available.
1417  * - Before kvm_intel.  module_init() is mapped to device_initcall() when
1418  *   it's built into the kernel.
1419  */
1420 subsys_initcall_sync(tdx_late_init);
```


### TDX Memory 
```cpp
38  * build_final_tdx_memory:      Build final TDX memory which contains all TDX
39  *                              capable memory blocks.
40  *
41  * Build final TDX memory which contains all TDX capable memory blocks by
42  * merging all sub-types of TDX capable memory that have been built.  After
43  * this function, all TDX capable memory blocks will be in @tmem_all.  In case
44  * of any error, all TDX memory intances are destroyed internally.
45  */      
46 int __init build_final_tdx_memory(void)
47 {
48         int ret;
49 
50         tdx_memory_init(&tmem_all);
51 
52         ret = merge_subtype_tdx_memory(&tmem_all, &tmem_sysmem,
53                         "system memory");
54         if (ret)
55                 goto err;
56 
57 #ifdef CONFIG_ENABLE_TDX_FOR_X86_PMEM_LEGACY
58         ret = merge_subtype_tdx_memory(&tmem_all, &tmem_legacy_pmem,
59                         "legacy PMEM");
60 #endif
61         if (ret)
62                 goto err;
63 
64         return 0;
65 err:
66         tdx_memory_destroy(&tmem_all);
67         cleanup_subtype_tdx_memory();
68         return ret;
69 }
```


```cpp
1370 /**
1371  * tdx_memory_merge:    Merge two TDX memory instances to one
1372  *
1373  * @tmem_dst:   The first TDX memory as destination
1374  * @tmem_src:   The second TDX memory as source
1375  *
1376  * Merge all TDX memory blocks in @tmem_src to @tmem_dst.  This allows caller
1377  * to build multiple intermediate TDX memory instances based on TDX memory type
1378  * (for instance, system memory, or x86 legacy PMEM) and/or NUMA locality, and
1379  * merge them together as final TDX memory to generate final TDMRs.
1380  *
1381  * On success, @tmem_src will be empty.  In case of any error, some TDX memory
1382  * blocks in @tmem_src may have already been moved to @tmem_dst.  Caller is
1383  * responsible for destroying both @tmem_src and @tmem_dst.
1384  */
1385 int __init tdx_memory_merge(struct tdx_memory *tmem_dst,
1386                 struct tdx_memory *tmem_src)
1387 {
1388         while (!list_empty(&tmem_src->tmb_list)) {
1389                 struct tdx_memblock *tmb = list_first_entry(&tmem_src->tmb_list,
1390                                 struct tdx_memblock, list);
1391                 int ret;
1392 
1393                 list_del(&tmb->list);
1394 
1395                 ret = tdx_memory_add_block(tmem_dst, tmb);
1396                 if (ret) {
1397                         /*
1398                          * Add @tmb back to @tmem_src, so it can be properly
1399                          * freed by caller.
1400                          */
1401                         list_add(&tmb->list, &tmem_src->tmb_list);
1402                         return ret;
1403                 }
1404         }
1405 
1406         return 0;
1407 }
```

We have two types of memory that can be used for TDX memory: legacy PMEM and system physical memory 
ranges that have been configured on the early init phase. 


## Final Initialization 
```cpp
1281         tdmr_info = kcalloc(tdx_tdsysinfo->max_tdmrs, sizeof(*tdmr_info),
1282                         GFP_KERNEL);
1283         if (!tdmr_info) {
1284                 ret = -ENOMEM;
1285                 goto out;
1286         }
1287 
1288         /* construct all TDMRs */
1289         desc.max_tdmr_num = tdx_tdsysinfo->max_tdmrs;
1290         desc.pamt_entry_size[TDX_PG_4K] = tdx_tdsysinfo->pamt_entry_size;
1291         desc.pamt_entry_size[TDX_PG_2M] = tdx_tdsysinfo->pamt_entry_size;
1292         desc.pamt_entry_size[TDX_PG_1G] = tdx_tdsysinfo->pamt_entry_size;
1293         desc.max_tdmr_rsvd_area_num = tdx_tdsysinfo->max_reserved_per_tdmr;
1294 
1295         ret = construct_tdx_tdmrs(tdx_cmrs, tdx_nr_cmrs, &desc, tdmr_info,
1296                         &tdx_nr_tdmrs);
```

The number of TDMR region is set by BIOS and cannot exceed that number. 

```cpp
 17 /*
 18  * TDX module descriptor.  Those are TDX module's TDMR related global
 19  * characteristics, which impact constructing TDMRs.
 20  */      
 21 struct tdx_module_descriptor {
 22         int max_tdmr_num;
 23         int pamt_entry_size[TDX_PG_MAX];
 24         int max_tdmr_rsvd_area_num;
 25 };       
 26 
```

### Construct TDMR 
```cpp
 85 /**
 86  * construct_tdx_tdmrs: Construct final TDMRs to cover all TDX memory
 87  *
 88  * @cmr_array:          Arrry of CMR entries
 89  * @cmr_num:            Number of CMR entries
 90  * @desc:               TDX module descriptor for constructing final TMDRs
 91  * @tdmr_info_array:    Array of final TDMRs
 92  * @tdmr_num:           Number of final TDMRs
 93  *
 94  * Construct final TDMRs to cover all TDX memory blocks in @tmem_all.
 95  * Caller needs to allocate enough storage for @tdmr_info_array, i.e. by
 96  * allocating enough entries indicated by desc->max_tdmr_num.
 97  *
 98  * Upon success, all TDMRs are stored in @tdmr_info_array, with @tdmr_num
 99  * indicting the actual TDMR number.
100  */
101 int __init construct_tdx_tdmrs(struct cmr_info *cmr_array, int cmr_num,
102                 struct tdx_module_descriptor *desc,
103                 struct tdmr_info *tdmr_info_array, int *tdmr_num)
104 {
105         int ret = 0;
106         int i;
107         struct tdx_memblock *tmb;
108 
109         /* No TDX memory available */
110         if (list_empty(&tmem_all.tmb_list))
111                 return -EFAULT;
112 
113         ret = tdx_memory_construct_tdmrs(&tmem_all, cmr_array, cmr_num,
114                         desc, tdmr_info_array, tdmr_num);
115         if (ret) {
116                 pr_err("Failed to construct TDMRs\n");
117                 goto out;
118         }
119 
120         i = 0;
121         list_for_each_entry(tmb, &tmem_all.tmb_list, list) {
122                 pr_info("TDX TDMR[%2d]: base 0x%016lx size 0x%016lx\n",
123                         i, tmb->start_pfn << PAGE_SHIFT,
124                         tmb->end_pfn << PAGE_SHIFT);
125                 if (tmb->pamt)
126                         pr_info("TDX PAMT[%2d]: base 0x%016lx size 0x%016lx\n",
127                                 i, tmb->pamt->pamt_pfn << PAGE_SHIFT,
128                                 tmb->pamt->total_pages << PAGE_SHIFT);
129                 i++;
130         }
131 
132 out:
133         /*
134          * Keep @tmem_all if constructing TDMRs was successfully done, since
135          * memory hotplug needs it to check whether new memory can be added
136          * or not.
137          */
138         if (ret)
139                 tdx_memory_destroy(&tmem_all);
140         return ret;
141 }
```


```cpp
1410  * tdx_memory_construct_tdmrs:  Construct final TDMRs to cover all TDX memory
1411  *                              blocks in final TDX memory
1412  *
1413  * @tmem:               The final TDX memory
1414  * @cmr_array:          Array of CMR entries
1415  * @cmr_num:            Number of CMR entries
1416  * @desc:               TDX module descriptor for constructing final TMDRs
1417  * @tdmr_info_array:    Array of constructed final TDMRs
1418  * @tdmr_num:           Number of final TDMRs
1419  *             
1420  * Construct final TDMRs to cover all TDX memory blocks in final TDX memory,
1421  * based on CMR info and TDX module descriptor.  Caller is responsible for
1422  * allocating enough space for array of final TDMRs @tdmr_info_array (i.e. by
1423  * allocating enough space based on @desc.max_tdmr_num).
1424  *
1425  * Upon success, all final TDMRs will be stored in @tdmr_info_array, and
1426  * @tdmr_num will have the actual number of TDMRs.  On failure, @tmem internal
1427  * state is cleared, and caller is responsible for destroying it.
1428  */
1429 int __init tdx_memory_construct_tdmrs(struct tdx_memory *tmem,
1430                 struct cmr_info *cmr_array, int cmr_num,
1431                 struct tdx_module_descriptor *desc,
1432                 struct tdmr_info *tdmr_info_array, int *tdmr_num)
1433 {              
1434         struct tdmr_range_ctx tr_ctx;
1435         int ret;
1436 
1437         BUILD_BUG_ON(sizeof(struct tdmr_info) != 512);
1438 
1439         /*
1440          * Sanity check TDX module descriptor.  TDX module should have the
1441          * architectural values in TDX spec.
1442          */
1443         if (WARN_ON_ONCE((desc->max_tdmr_num != TDX_MAX_NR_TDMRS) ||
1444                 (desc->max_tdmr_rsvd_area_num != TDX_MAX_NR_RSVD_AREAS) ||
1445                 (desc->pamt_entry_size[TDX_PG_4K] != TDX_PAMT_ENTRY_SIZE) ||
1446                 (desc->pamt_entry_size[TDX_PG_2M] != TDX_PAMT_ENTRY_SIZE) ||
1447                 (desc->pamt_entry_size[TDX_PG_1G] != TDX_PAMT_ENTRY_SIZE)))
1448                 return -EINVAL;
1449 
1450         /*
1451          * Sanity check number of CMR entries.  It should not exceed maximum
1452          * value defined by TDX spec.
1453          */
1454         if (WARN_ON_ONCE((cmr_num > TDX_MAX_NR_CMRS) || (cmr_num <= 0)))
1455                 return -EINVAL;
1456 
1457         ret = sanity_check_cmrs(tmem, cmr_array, cmr_num);
1458         if (ret)
1459                 return ret;
1460 
1461         /* Generate a list of TDMR ranges to cover all TDX memory blocks */
1462         tdmr_range_ctx_init(&tr_ctx, tmem);
1463         ret = generate_tdmr_ranges(&tr_ctx);
1464         if (ret)
1465                 goto tr_ctx_err;
1466 
1467         /*
1468          * Shrink number of TDMR ranges in case it exceeds maximum
1469          * number of TDMRs that TDX can support.
1470          */
1471         ret = shrink_tdmr_ranges(&tr_ctx, desc->max_tdmr_num);
1472         if (ret)
1473                 goto tr_ctx_err;
1474 
1475         /* TDMR ranges are ready.  Prepare to construct TDMRs. */
1476         ret = construct_tdmrs_prepare(tmem, desc->max_tdmr_num);
1477         if (ret)
1478                 goto construct_tdmrs_err;
1479 
1480         /* Distribute TDMRs across all TDMR ranges */
1481         ret = distribute_tdmrs_across_tdmr_ranges(&tr_ctx, desc->max_tdmr_num,
1482                         tdmr_info_array);
1483         if (ret)
1484                 goto construct_tdmrs_err;
1485 
1486         /*
1487          * Allocate PAMTs for all TDMRs, and set up PAMT info in
1488          * all TDMR_INFO entries.
1489          */
1490         ret = setup_pamts_across_tdmrs(tmem, desc->pamt_entry_size,
1491                         tdmr_info_array);
1492         if (ret)
1493                 goto construct_tdmrs_err;
1494 
1495         /* Set up reserved areas for all TDMRs */
1496         ret = fillup_reserved_areas_across_tdmrs(tmem, tdmr_info_array,
1497                         desc->max_tdmr_rsvd_area_num);
1498         if (ret)
1499                 goto construct_tdmrs_err;
1500 
1501         /* Constructing TDMRs done.  Set up the actual TDMR number */
1502         *tdmr_num = tmem->tdmr_num;
1503 
1504         /*
1505          * Discard TDMR ranges.  They are useless after
1506          * constructing TDMRs is done.
1507          */
1508         tdmr_range_ctx_destroy(&tr_ctx);
1509 
1510         return 0;
1511 
1512 construct_tdmrs_err:
1513         construct_tdmrs_cleanup(tmem);
1514 tr_ctx_err:
1515         tdmr_range_ctx_destroy(&tr_ctx);
1516         return ret;
1517 }
```

Before it builds up TDMR range data structures, the module checks whether TDX memory block (tmem)
should reside inside the CMR.

```cpp
  37 /*
  38  * Sanity check whether all TDX memory blocks are fully covered by CMRs.
  39  * Only convertible memory can truly be used by TDX.
  40  */
  41 static int __init sanity_check_cmrs(struct tdx_memory *tmem,
  42                 struct cmr_info *cmr_array, int cmr_num)
  43 {
  44         struct tdx_memblock *tmb;
  45 
  46         /*
  47          * Check CMRs against entire TDX memory, rather than against individual
  48          * TDX memory block to allow more flexibility, i.e. to allow adding TDX
  49          * memory block before CMR info is available.
  50          */
  51         list_for_each_entry(tmb, &tmem->tmb_list, list)
  52                 if (!phys_range_covered_by_cmrs(cmr_array, cmr_num,
  53                                 tmb->start_pfn << PAGE_SHIFT,
  54                                 tmb->end_pfn << PAGE_SHIFT))
  55                         break;
  56 
  57         /* Return success if all blocks have passed CMR check */
  58         if (list_entry_is_head(tmb, &tmem->tmb_list, list))
  59                 return 0;
  60 
  61         /*
  62          * TDX cannot be enabled in this case.  Explicitly give a message
  63          * so user can know the reason of failure.
  64          */
  65         pr_info("Memory [0x%lx, 0x%lx] not fully covered by CMR\n",
  66                                 tmb->start_pfn << PAGE_SHIFT,
  67                                 tmb->end_pfn << PAGE_SHIFT);
  68         return -EFAULT;
  69 }
```

It needs to build up tdmr_range information using the tmem information gathered through 
the initialization. Important data structure is tdmr_range_cts containing all information of 
tdmr range needed to build TDMR later. 

```cpp
 106 /*
 107  * Context of a set of TDMR ranges.  It is generated to cover all TDX memory
 108  * blocks to assist constructing TDMRs.  It can be discarded after TDMRs are
 109  * generated.
 110  */
 111 struct tdmr_range_ctx {
 112         struct tdx_memory *tmem;
 113         struct list_head tr_list;
 114         int tr_num;
 115 };
```

```cpp
 187  * Generate a list of TDMR ranges for given TDX memory @tmem, as a preparation
 188  * to construct final TDMRs.
 189  */
 190 static int __init generate_tdmr_ranges(struct tdmr_range_ctx *tr_ctx)
 191 {
 192         struct tdx_memory *tmem = tr_ctx->tmem;
 193         struct tdx_memblock *tmb;
 194         struct tdmr_range *last_tr = NULL;
 195 
 196         list_for_each_entry(tmb, &tmem->tmb_list, list) {
 197                 struct tdmr_range *tr;
 198 
 199                 /* Create a new TDMR range for the first @tmb */
 200                 if (!last_tr) {
 201                         tr = tdmr_range_create(tmb, false);
 202                         if (!tr)
 203                                 return -ENOMEM;
 204                         /* Add to tail to keep TDMR ranges in ascending order */
 205                         list_add_tail(&tr->list, &tr_ctx->tr_list);
 206                         tr_ctx->tr_num++;
 207                         last_tr = tr;
 208                         continue;
 209                 }
 210 
 211                 /*
 212                  * Always create a new TDMR range if @tmb belongs to a new NUMA
 213                  * node, to ensure the TDMR and the PAMT which covers it are on
 214                  * the same NUMA node.
 215                  */
 216                 if (tmb->nid != last_tr->last_tmb->nid) {
 217                         /*
 218                          * If boundary of two NUMA nodes falls into the middle
 219                          * of 1G area, then part of @tmb has already been
 220                          * covered by first node's last TDMR range.  In this
 221                          * case, shrink the new TDMR range.
 222                          */
 223                         bool shrink_start = TDX_MEMBLOCK_TDMR_START(tmb) <
 224                                 last_tr->end_1g ? true : false;
 225 
 226                         tr = tdmr_range_create(tmb, shrink_start);
 227                         if (!tr)
 228                                 return -ENOMEM;
 229                         list_add_tail(&tr->list, &tr_ctx->tr_list);
 230                         tr_ctx->tr_num++;
 231                         last_tr = tr;
 232                         continue;
 233                 }
 234 
 235                 /*
 236                  * Always extend existing TDMR range to cover new @tmb if part
 237                  * of @tmb has already been covered, regardless memory type of
 238                  * @tmb.
 239                  */
 240                 if (TDX_MEMBLOCK_TDMR_START(tmb) < last_tr->end_1g) {
 241                         tdmr_range_extend(last_tr, tmb);
 242                         continue;
 243                 }
 244 
 245                 /*
 246                  * By reaching here, the new @tmb is in the same NUMA node, and
 247                  * is not covered by last TDMR range.  Always create a new TDMR
 248                  * range in this case, so that final TDMRs won't cross TDX
 249                  * memory block boundary.
 250                  */
 251                 tr = tdmr_range_create(tmb, false);
 252                 if (!tr)
 253                         return -ENOMEM;
 254                 list_add_tail(&tr->list, &tr_ctx->tr_list);
 255                 tr_ctx->tr_num++;
 256                 last_tr = tr;
 257         }
 258 
 259         return 0;
 260 }
```

Nothing interesting in the above code. Create new tdmr range based on the tmem. One interesting 
point is kernel spawns new tdmr range whenever the numa changes. 

```cpp
 117 /*
 118  * Create a TDMR range which covers the TDX memory block @tmb.  @shrink_start
 119  * indicates whether to shrink first 1G, i.e. when boundary of @tmb and
 120  * previous block falls into the middle of 1G area, but a new TDMR range for
 121  * @tmb is desired.
 122  */
 123 static struct tdmr_range * __init tdmr_range_create(
 124                 struct tdx_memblock *tmb, bool shrink_start)
 125 {       
 126         struct tdmr_range *tr = kzalloc(sizeof(*tr), GFP_KERNEL);
 127         
 128         if (!tr)
 129                 return NULL;
 130         
 131         INIT_LIST_HEAD(&tr->list);
 132         
 133         tr->start_1g = TDX_MEMBLOCK_TDMR_START(tmb);
 134         if (shrink_start)
 135                 tr->start_1g += TDMR_ALIGNMENT;
 136         tr->end_1g = TDX_MEMBLOCK_TDMR_END(tmb);
 137         tr->nid = tmb->nid;
 138         tr->first_tmb = tr->last_tmb = tmb;
 139         
 140         return tr;
 141 }
```


### Distribute tdmrs

```cpp
 536 /*
 537  * Second step of constructing final TDMRs:
 538  *
 539  * Distribute TDMRs on TDMR ranges saved in array as even as possible.  It walks
 540  * through all TDMR ranges, and calculate number of TDMRs for given TDMR range
 541  * by comparing TDMR range's size and total size of all TDMR ranges.  Upon
 542  * success, the distributed TDMRs' address ranges will be updated to each entry
 543  * in @tdmr_array.
 544  */
 545 static int __init distribute_tdmrs_across_tdmr_ranges(
 546                 struct tdmr_range_ctx *tr_ctx, int max_tdmr_num,
 547                 struct tdmr_info *tdmr_info_array)
 548 {
 549         struct tdx_memory *tmem = tr_ctx->tmem;
 550         struct tdx_tdmr *tdmr_array = tmem->tdmr_array;
 551         struct tdmr_range *tr;
 552         unsigned long remain_1g_areas;
 553         int remain_tdmr_num;
 554         int last_tdmr_idx;
 555 
 556         if (WARN_ON_ONCE(!tdmr_array))
 557                 return -EFAULT;
 558 
 559         /* Distribute TDMRs on basis of 'struct tdmr_range' one by one. */
 560         remain_1g_areas =
 561                 TDMR_SIZE_TO_1G_AREAS(calculate_total_tdmr_range_size(tr_ctx));
 562         if (!remain_1g_areas)
 563                 return 0;
 564 
 565         remain_tdmr_num = max_tdmr_num;
 566         last_tdmr_idx = 0;
 567         list_for_each_entry(tr, &tr_ctx->tr_list, list) {
 568                 unsigned long tr_1g_areas;
 569                 int tdmr_num_tr;
 570 
 571                 /*
 572                  * Always calculate number of TDMRs for this TDMR range using
 573                  * remaining number of TDMRs, and remaining total range of TDMR
 574                  * ranges, so that number of all TDMRs for all TDMR ranges won't
 575                  * exceed @max_tdmr_num.
 576                  */
 577                 tr_1g_areas = TDMR_RANGE_TO_1G_AREAS(tr->start_1g, tr->end_1g);
 578                 tdmr_num_tr = tr_1g_areas * remain_tdmr_num / remain_1g_areas;
 579 
 580                 /*
 581                  * It's possible @tdmr_num_tr can be 0, when this TDMR range is
 582                  * too small, comparing to total TDMR ranges.  In this case,
 583                  * just use one TDMR to cover it.
 584                  */
 585                 if (!tdmr_num_tr)
 586                         tdmr_num_tr = 1;
 587 
 588                 /*
 589                  * When number of all TDMR range's total 1G areas is smaller
 590                  * than maximum TDMR number, the TDMR number distributed to one
 591                  * TDMR range will be larger than its 1G areas.  Reduce TDMR
 592                  * number to number of 1G areas in this case.
 593                  */
 594                 if (tdmr_num_tr > tr_1g_areas)
 595                         tdmr_num_tr = tr_1g_areas;
 596 
 597                 /* Distribute @tdmr_num_tr TDMRs for this TDMR range */
 598                 tdmr_range_distribute_tdmrs(tr, tdmr_num_tr,
 599                                 tdmr_array + last_tdmr_idx);
 600 
 601                 last_tdmr_idx += tdmr_num_tr;
 602 
 603                 remain_1g_areas -= tr_1g_areas;
 604                 remain_tdmr_num -= tdmr_num_tr;
 605         }
 606 
 607         WARN_ON_ONCE(last_tdmr_idx > max_tdmr_num);
 608         WARN_ON_ONCE(remain_1g_areas);
 609 
 610         /* Save actual number of TDMRs */
 611         tmem->tdmr_num = last_tdmr_idx;
 612 
 613         /* Set up base and size to all TDMR_INFO entries */
 614         tmem_setup_tdmr_info_address_ranges(tmem, tdmr_info_array);
 615 
 616         return 0;
 617 }

```


### Allocate PAMT for TDMR
```cpp
setup_pamts_across_tdmrs

```
