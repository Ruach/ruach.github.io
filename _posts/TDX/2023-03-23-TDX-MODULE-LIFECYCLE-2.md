---
layout: post
title: "TDX Module Life Cycle Part 2"
categories: [Confidential Computing, Intel TDX, KVM, QEMU] 
---

In previous posts, I discussed the initialization of the TDX module using 
TDH_SYS_INIT SEAMCALL. As depicted in the image below, several additional 
configuration steps are necessary for the TDX module initialization sequence, 
which will be addressed in this post.

![TDX_MODULE_INIT](/assets/img/TDX//tdx-module-init.png)

## TDX Module Global Configuration 
After initializing all logical processors on the platform, global data structure
for TDX module should be configured and initialized. This includes TDMR, PAMT 
and HKID for TDX Module.

### TDMR 
Trust Domain Memory Region (TDMR) is memory range that can be converted between
TD-VM pages and normal pages. The memory pages that does not belong to TDMR can
not be converted to TD-VM page, especially private pages. TDMR should meet below
specific requirements: 
1. There is no requirement for TMDRs to cover all CMRs.
2. Each TDMR has its own size which must be a multiple of 1GB.
3. TDMR memory, except for reserved areas, must be convertible as checked by
MCHECK (i.e., every TDMR page must reside within a CMR).
4. TDMRs are configured at platform scope (no separate configuration per package).
5. TDMRs should not be overlapped with each other.


### PAMT
The Physical Address Metadata Table (PAMT) is the metadata of **every physical 
page in TDMR**. A page metadata include page type, page size, assignment to a TD,
and other attributes.

1. PAMT area must reside in convertible memory (CMR)
2. PAMT areas must not overlap with TDMR non-reserved areas; however, they may 
reside within TDMR reserved areas (as long as these are convertible).
3. PAMT areas must not overlap with each other.


>For each 1GB of TDMR physical memory, there is a corresponding PAMT block. 
A PAMT block is **logically** arranged in a three-level tree structure of PAMT 
entries. Levels 0 through 2 (PAMT_4K, PAMT_2M and PAMT_1G) correspond to 4KB, 
2MB and 1GB physical TDMR pages, respectively. **Physically**, for each TDMR the
design includes three arrays of PAMT entries, one for each PAMT level. This aims
to simplify VMM memory allocation. A logical PAMT block has one entry from the 
PAMT_1G array, 512 entries from the PAMT_2M array, and 512^2 entries from the 
PAMT_4K array.

Each TDMR is defined as controlled by a (logically) single Physical Address 
Metadata Table (PAMT). Therefore, three levels of PAMT should be configured for 
every TDMR. 

### Reserved area
The granularity of the TDMR is 1GB. However, there can be a requirement for the
host VMM to be able to allocate memory at granularities smaller than 1GB. To 
support the two requirements above, the TDX module’s design allows arbitrary
reserved areas within TDMRs. Reserved areas are still covered by PAMT. However,
during initialization their respective PAMT entries are marked with a PT_RSVD 
page type, so pages in reserved areas are not used by the Intel TDX module for 
allocating private memory pages (but they can be used for PAMT areas). Only the
non-reserved parts of a TDMR are required to be inside CMRs, which means the 
reserved area can be located outside of CMR. Why? Sometimes one TDMR cannot be 
covered by one CMR because of lack of memory space in that CMR. 

![CMR_TDMR](/assets/img/TDX//cmr_vs_tdmr.png)

## VMM Populates TDMRs for TDX Module
```cpp
static int init_tdx_module(void)
{
......
        /*
         * To avoid having to modify the page allocator to distinguish
         * TDX and non-TDX memory allocation, convert all memory regions
         * in memblock to TDX memory to make sure all pages managed by
         * the page allocator are TDX memory.
         *
         * Sanity check all memory regions are fully covered by CMRs to
         * make sure they are truly convertible.
         */
        ret = check_memblock_tdx_convertible();
        if (ret)
                goto out;
        
        /* Prepare enough space to construct TDMRs */
        tdmr_array = alloc_tdmr_array(&tdmr_array_sz);
        if (!tdmr_array) { 
                ret = -ENOMEM;
                goto out;
        }

        /* Construct TDMRs to cover all memory regions in memblock */
        ret = construct_tdmrs_memeblock(tdmr_array, &tdmr_num);
        if (ret)
                goto out_free_tdmrs;

        /*
         * Reserve the first TDX KeyID as global KeyID to protect
         * TDX module metadata.
         */
        tdx_global_keyid = tdx_keyid_start;

        /* Pass the TDMRs and the global KeyID to the TDX module */
        ret = config_tdx_module(tdmr_array, tdmr_num, tdx_global_keyid);
        if (ret)
                goto out_free_pamts;
```

For TDH_SYS_CONFIG, the information about physical addresses of tdmr_info 
entries and private keyid for global encryption/decryption of TDX module is 
passed to the TDX Module through the SEAMCALL. Let's figure out how the host KVM
populate TDMR array for TDX Module. 

### Check memblock regions are convertible into TDMR 
Kernel at some point, before the buddy allocation is initialized, it manages 
all memories on the platform as MEMBLOCK. VMM populates the TDMR to cover all
MEMBLOCK regions that reside within the CMR.

```cpp
/*              
 * Check whether all memory regions in memblock are TDX convertible
 * memory.  Return 0 if all memory regions are convertible, or error.
 */     
static int check_memblock_tdx_convertible(void)
{               
        unsigned long start_pfn, end_pfn;
        int i;

        memblock_for_each_tdx_mem_pfn_range(i, &start_pfn, &end_pfn, NULL) {
                u64 start, end;

                start = start_pfn << PAGE_SHIFT;
                end = end_pfn << PAGE_SHIFT;
                if (!range_covered_by_cmr(tdx_cmr_array, tdx_cmr_num, start,
                                        end)) {
                        pr_err("[0x%llx, 0x%llx) is not fully convertible memory\n",
                                        start, end);
                        return -EINVAL;
                }
        }

        return 0;
}

/*
 * Walks over all memblock memory regions that are intended to be
 * converted to TDX memory.  Essentially, it is all memblock memory
 * regions excluding the low memory below 1MB.
 *
 * This is because on some TDX platforms the low memory below 1MB is
 * not included in CMRs.  Excluding the low 1MB can still guarantee
 * that the pages managed by the page allocator are always TDX memory,
 * as the low 1MB is reserved during kernel boot and won't end up to
 * the ZONE_DMA (see reserve_real_mode()).
 */
#define memblock_for_each_tdx_mem_pfn_range(i, p_start, p_end, p_nid)   \
        for_each_mem_pfn_range(i, MAX_NUMNODES, p_start, p_end, p_nid)  \
                if (!pfn_range_skip_lowmem(p_start, p_end))
```

Iterator literally iterates all memblock regions, but the low mem region. It 
checks if all memblocks can be converted into TDX memory, which means that the 
start and end addresses of all available memblock should be **within the CMR**.

## Generate TDMRs and Set Up PAMT
If all memblocks are able to be converted to the TDX memories, then it generates
TDMRs to cover all memory regions in memblock. 

```cpp
/* 
 * Construct an array of TDMRs to cover all memory regions in memblock.
 * This makes sure all pages managed by the page allocator are TDX
 * memory.  The actual number of TDMRs is kept to @tdmr_num.
 */     
static int construct_tdmrs_memeblock(struct tdmr_info *tdmr_array,
                                     int *tdmr_num)
{
        int ret;

        ret = create_tdmrs(tdmr_array, tdmr_num);
        if (ret)
                goto err;
        
        ret = tdmrs_set_up_pamt_all(tdmr_array, *tdmr_num);
        if (ret)
                goto err;
                
        ret = tdmrs_set_up_rsvd_areas_all(tdmr_array, *tdmr_num);
        if (ret)
                goto err_free_pamts;

        return 0;
err_free_pamts:
        tdmrs_free_pamt_all(tdmr_array, *tdmr_num);
err:
        return ret;
}
```
Creating TDMRs consists of three steps: Create TDMR, Set-up PAMT for generated 
TDMR, Set-up reserved areas. Note that tdmr_array was already allocated by 
alloc_tdmr_array function.


### Create TDMRs
```cpp
static int create_tdmrs(struct tdmr_info *tdmr_array, int *tdmr_num)
{
        unsigned long start_pfn, end_pfn;
        int i, nid, tdmr_idx = 0;

        /*
         * Loop over all memory regions in memblock and create TDMRs to
         * cover them.  To keep it simple, always try to use one TDMR to
         * cover memory region.
         */
        memblock_for_each_tdx_mem_pfn_range(i, &start_pfn, &end_pfn, &nid) {
                struct tdmr_info *tdmr;
                u64 start, end;

                tdmr = tdmr_array_entry(tdmr_array, tdmr_idx);
                start = TDMR_ALIGN_DOWN(start_pfn << PAGE_SHIFT);
                end = TDMR_ALIGN_UP(end_pfn << PAGE_SHIFT);

                /*
                 * If the current TDMR's size hasn't been initialized,
                 * it is a new TDMR to cover the new memory region.
                 * Otherwise, the current TDMR has already covered the
                 * previous memory region.  In the latter case, check
                 * whether the current memory region has been fully or
                 * partially covered by the current TDMR, since TDMR is
                 * 1G aligned.
                 */
                if (tdmr->size) {
                        /*
                         * Loop to the next memory region if the current
                         * region has already fully covered by the
                         * current TDMR.
                         */
                        if (end <= tdmr_end(tdmr))
                                continue;

                        /*
                         * If part of the current memory region has
                         * already been covered by the current TDMR,
                         * skip the already covered part.
                         */
                        if (start < tdmr_end(tdmr))
                                start = tdmr_end(tdmr);

                        /*
                         * Create a new TDMR to cover the current memory
                         * region, or the remaining part of it.
                         */
                        tdmr_idx++;
                        if (tdmr_idx >= tdx_sysinfo.max_tdmrs)
                                return -E2BIG;

                        tdmr = tdmr_array_entry(tdmr_array, tdmr_idx);
                }

                tdmr->base = start;
                tdmr->size = end - start;
        }

        /* @tdmr_idx is always the index of last valid TDMR. */
        *tdmr_num = tdmr_idx + 1;

        return 0;
}
```

One TDMR can contain multiple memblock regions because it is 1G aligned
address range. To check whether one memblock region can be covered by this 
TDMR region, it aligns down and up the start and end addresses respectively.
If the current memblock region can be covered by the existing TDMR region, then 
it is included in the TDMR. If not, it generates another TDMR region. 

### Allocate PAMT for TDMR
```cpp
/* Allocate and set up PAMTs for all TDMRs */
static int tdmrs_set_up_pamt_all(struct tdmr_info *tdmr_array, int tdmr_num)
{
        int i, ret = 0;

        for (i = 0; i < tdmr_num; i++) {
                ret = tdmr_set_up_pamt(tdmr_array_entry(tdmr_array, i));
                if (ret)
                        goto err;
        }

        return 0;
err:
        tdmrs_free_pamt_all(tdmr_array, tdmr_num);
        return ret;
}
```

```cpp
static int tdmr_set_up_pamt(struct tdmr_info *tdmr)
{
        unsigned long pamt_base[TDX_PG_MAX];
        unsigned long pamt_size[TDX_PG_MAX];
        unsigned long tdmr_pamt_base;
        unsigned long tdmr_pamt_size;
        enum tdx_page_sz pgsz;
        struct page *pamt;
        int nid;

        nid = tdmr_get_nid(tdmr);

        /*
         * Calculate the PAMT size for each TDX supported page size
         * and the total PAMT size.
         */
        tdmr_pamt_size = 0;
        for (pgsz = TDX_PG_4K; pgsz < TDX_PG_MAX; pgsz++) {
                pamt_size[pgsz] = tdmr_get_pamt_sz(tdmr, pgsz);
                tdmr_pamt_size += pamt_size[pgsz];
        }

        /*
         * Allocate one chunk of physically contiguous memory for all
         * PAMTs.  This helps minimize the PAMT's use of reserved areas
         * in overlapped TDMRs.
         */
        pamt = alloc_contig_pages(tdmr_pamt_size >> PAGE_SHIFT, GFP_KERNEL,
                        nid, &node_online_map);
        if (!pamt)
                return -ENOMEM;

        /* Calculate PAMT base and size for all supported page sizes. */
        tdmr_pamt_base = page_to_pfn(pamt) << PAGE_SHIFT;
        for (pgsz = TDX_PG_4K; pgsz < TDX_PG_MAX; pgsz++) {
                pamt_base[pgsz] = tdmr_pamt_base;
                tdmr_pamt_base += pamt_size[pgsz];
        }

        tdmr->pamt_4k_base = pamt_base[TDX_PG_4K];
        tdmr->pamt_4k_size = pamt_size[TDX_PG_4K];
        tdmr->pamt_2m_base = pamt_base[TDX_PG_2M];
        tdmr->pamt_2m_size = pamt_size[TDX_PG_2M];
        tdmr->pamt_1g_base = pamt_base[TDX_PG_1G];
        tdmr->pamt_1g_size = pamt_size[TDX_PG_1G];

        return 0;
}
```

tdmr_set_up_pamt function is invoked for every TDMR and allocate PAMT pages 
based on the size of the TDMR. Because we don't know which page size will be 
used to map physical pages in the TDMR, PAMT should be ready for all possible 
sizes. Information about each level of PAMT is managed by the tdmr_info struct. 

### Set up reserved area within TDMR

```cpp
static int tdmrs_set_up_rsvd_areas_all(struct tdmr_info *tdmr_array,
                                      int tdmr_num)
{
        int i;

        for (i = 0; i < tdmr_num; i++) {
                int ret;

                ret = tdmr_set_up_rsvd_areas(tdmr_array_entry(tdmr_array, i),
                                tdmr_array, tdmr_num);
                if (ret)
                        return ret;
        }

        return 0;
}
```
It iterates all TDMR and check whether the TDMR requires reserved area. 


```cpp
/* Set up reserved areas for a TDMR, including memory holes and PAMTs */
static int tdmr_set_up_rsvd_areas(struct tdmr_info *tdmr,
                                  struct tdmr_info *tdmr_array,
                                  int tdmr_num)
{
        unsigned long start_pfn, end_pfn;
        int rsvd_idx, i, ret = 0;
        u64 prev_end;

        /* Mark holes between memory regions as reserved */
        rsvd_idx = 0;
        prev_end = tdmr_start(tdmr);
        memblock_for_each_tdx_mem_pfn_range(i, &start_pfn, &end_pfn, NULL) {
                u64 start, end;

                start = start_pfn << PAGE_SHIFT;
                end = end_pfn << PAGE_SHIFT;

                /* Break if this region is after the TDMR */
                if (start >= tdmr_end(tdmr))
                        break;

                /* Exclude regions before this TDMR */
                if (end < tdmr_start(tdmr))
                        continue;

                /*
                 * Skip if no hole exists before this region. "<=" is
                 * used because one memory region might span two TDMRs
                 * (when the previous TDMR covers part of this region).
                 * In this case the start address of this region is
                 * smaller than the start address of the second TDMR.
                 *
                 * Update the prev_end to the end of this region where
                 * the possible memory hole starts.
                 */
                if (start <= prev_end) {
                        prev_end = end;
                        continue;
                }

                /* Add the hole before this region */
                ret = tdmr_add_rsvd_area(tdmr, &rsvd_idx, prev_end,
                                start - prev_end);
                if (ret)
                        return ret;

                prev_end = end;
        }

        /* Add the hole after the last region if it exists. */
        if (prev_end < tdmr_end(tdmr)) {
                ret = tdmr_add_rsvd_area(tdmr, &rsvd_idx, prev_end,
                                tdmr_end(tdmr) - prev_end);
                if (ret)
                        return ret;
        }

        /*
         * If any PAMT overlaps with this TDMR, the overlapping part
         * must also be put to the reserved area too.  Walk over all
         * TDMRs to find out those overlapping PAMTs and put them to
         * reserved areas.
         */
        for (i = 0; i < tdmr_num; i++) {
                struct tdmr_info *tmp = tdmr_array_entry(tdmr_array, i);
                u64 pamt_start, pamt_end;

                pamt_start = tmp->pamt_4k_base;
                pamt_end = pamt_start + tmp->pamt_4k_size +
                        tmp->pamt_2m_size + tmp->pamt_1g_size;

                /* Skip PAMTs outside of the given TDMR */
                if ((pamt_end <= tdmr_start(tdmr)) ||
                                (pamt_start >= tdmr_end(tdmr)))
                        continue;

                /* Only mark the part within the TDMR as reserved */
                if (pamt_start < tdmr_start(tdmr))
                        pamt_start = tdmr_start(tdmr);
                if (pamt_end > tdmr_end(tdmr))
                        pamt_end = tdmr_end(tdmr);

                ret = tdmr_add_rsvd_area(tdmr, &rsvd_idx, pamt_start,
                                pamt_end - pamt_start);
                if (ret)
                        return ret;
        }

        /* TDX requires reserved areas listed in address ascending order */
        sort(tdmr->reserved_areas, rsvd_idx, sizeof(struct tdmr_reserved_area),
                        rsvd_area_cmp_func, NULL);

        return 0;
}
```


## Sets Up TDMR and HKID on TDX Module
```cpp
    case TDH_SYS_CONFIG_LEAF:
    {   
        hkid_api_input_t global_private_hkid;
        global_private_hkid.raw = local_data->vmm_regs.r8;
        
        local_data->vmm_regs.rax = tdh_sys_config(local_data->vmm_regs.rcx,
                                                 local_data->vmm_regs.rdx,
                                                 global_private_hkid);
        break;
    }   
```

```cpp
api_error_type tdh_sys_config(uint64_t tdmr_info_array_pa,
                             uint64_t num_of_tdmr_entries,
                             hkid_api_input_t global_private_hkid)
{
    // Temporary Variables
    tdmr_info_entry_t*   tdmr_info_p;   // Pointer to TDMR info
    tdmr_info_entry_t*   tdmr_info_copy;// Pointer to TDMR info array
    bool_t               tdmr_info_p_init = false;
    pa_t                 tdmr_info_pa = {.raw = tdmr_info_array_pa};  // Physical address of an array of physical addresses of the TDMR info structure
    uint64_t*            tdmr_pa_array = NULL; // Pointer to an array of physical addresses of the TDMR info structure
    uint16_t             hkid = global_private_hkid.hkid;
    bool_t               global_lock_acquired = false;
    tdx_module_global_t* tdx_global_data_ptr = get_global_data();

    api_error_type       retval = TDX_SYS_BUSY;
    ......
        if ((global_private_hkid.reserved != 0) || !is_private_hkid(hkid))
    {
        TDX_ERROR("HKID 0x%x is not private\n", hkid);
        retval = api_error_with_operand_id(TDX_OPERAND_INVALID, OPERAND_ID_R8);
        goto EXIT;
    }

    tdx_global_data_ptr->kot.entries[hkid].state = KOT_STATE_HKID_RESERVED;
    tdx_global_data_ptr->hkid = hkid;
        
    tdmr_pa_array = map_pa(tdmr_info_pa.raw_void, TDX_RANGE_RO);
    tdmr_info_p_init = true; 
    
    // map only 2 tdmr entries each time
    pa_t tdmr_entry;
    pamt_data_t pamt_data_array[MAX_TDMRS];
    api_error_type err;
    
    tdmr_info_copy = tdx_global_data_ptr->tdmr_info_copy;
    
    for(uint64_t i = 0; i < num_of_tdmr_entries; i++)
    {

        tdmr_entry.raw = tdmr_pa_array[i];
        retval = shared_hpa_check_with_pwr_2_alignment(tdmr_entry, TDMR_INFO_ENTRY_PTR_ARRAY_ALIGNMENT);
        if (retval != TDX_SUCCESS)
        {
            retval = api_error_with_operand_id(retval, OPERAND_ID_RCX);
            TDX_ERROR("TDMR entry PA is not a valid shared HPA pa=0x%llx, error=0x%llx\n", tdmr_entry.raw, retval);
            goto EXIT;
        }

        tdmr_info_p = (tdmr_info_entry_t*)map_pa(tdmr_entry.raw_void, TDX_RANGE_RO);
        copy_tdmr_info_entry (tdmr_info_p, &tdmr_info_copy[i]);
        free_la(tdmr_info_p);


        if ((err = check_and_set_tdmrs(tdmr_info_copy, i, pamt_data_array)) != TDX_SUCCESS)
        {
            TDX_ERROR("Check and set TDMRs failed\n");
            retval = err;
            goto EXIT;
        }
        update_pamt_array(tdmr_info_copy, pamt_data_array, (uint32_t)i); // save tdmr's pamt data
    }

    tdx_global_data_ptr->num_of_tdmr_entries = (uint32_t)num_of_tdmr_entries;

    // ALL_CHECKS_PASSED:  The function is guaranteed to succeed

    // Complete CPUID handling
    for (uint32_t i = 0; i < MAX_NUM_CPUID_LOOKUP; i++)
    {
        for (uint32_t j = 0; j < 4; j++)
        {
            uint32_t cpuid_value = tdx_global_data_ptr->cpuid_values[i].values.values[j];

            // Clear the bits that will be later virtualized as FIXED0 or DYNAMIC
            cpuid_value &= ~cpuid_lookup[i].fixed0_or_dynamic.values[j];

            // Set to 1 any bits that will be later virtualized as FIXED1
            cpuid_value |= cpuid_lookup[i].fixed1.values[j];

            tdx_global_data_ptr->cpuid_values[i].values.values[j] = cpuid_value;
        }
    }

    // Prepare state variables for TDHSYSKEYCONFIG
    tdx_global_data_ptr->pkg_config_bitmap = 0ULL;

    // Mark the system initialization as done
    tdx_global_data_ptr->global_state.sys_state = SYSCONFIG_DONE;
    retval = TDX_SUCCESS;

EXIT:

    if (global_lock_acquired)
    {
        release_sharex_lock_ex(&tdx_global_data_ptr->global_lock);
    }

    if (tdmr_info_p_init)
    {
        free_la(tdmr_pa_array);
    }

    return retval;
}
```

The first parameter tdmr_info_array_pa is the array containing **physical**
addresses of the **tdmr_info** maintained by the kernel. It has been passed as a
physical addresses, so it should be remapped by the TDX module before accessing 
them to get the TDMR information passed from the host KVM side. After mapping 
the physical addresses, TDX Module accesses them through **tmdr_info_entry_t**
struct pointer. TDMR information is copied to the tdmr_info_copy field of the 
tdx_global_data_ptr. Note that this mapping is populated through the keyhole 
by the map_pa function. 

```cpp
typedef struct PACKED tdmr_info_entry_s
{       
    uint64_t tdmr_base;    /**< Base address of the TDMR (HKID bits must be 0). 1GB aligned. */
    uint64_t tdmr_size;    /**< Size of the CMR, in bytes. 1GB aligned. */
    uint64_t pamt_1g_base; /**< Base address of the PAMT_1G range associated with the above TDMR (HKID bits must be 0). 4K aligned. */
    uint64_t pamt_1g_size; /**< Size of the PAMT_1G range associated with the above TDMR. 4K aligned. */
    uint64_t pamt_2m_base; /**< Base address of the PAMT_2M range associated with the above TDMR (HKID bits must be 0). 4K aligned. */
    uint64_t pamt_2m_size; /**< Size of the PAMT_2M range associated with the above TDMR. 4K aligned. */
    uint64_t pamt_4k_base; /**< Base address of the PAMT_4K range associated with the above TDMR (HKID bits must be 0). 4K aligned. */
    uint64_t pamt_4k_size; /**< Size of the PAMT_4K range associated with the above TDMR. 4K aligned. */
        
    struct
    {
        uint64_t offset; /**< Offset of reserved range 0 within the TDMR. 4K aligned. */
        uint64_t size;   /**< Size of reserved range 0 within the TDMR. A size of 0 indicates a null entry. 4K aligned. */
    } rsvd_areas[MAX_RESERVED_AREAS];

} tdmr_info_entry_t;
```

### Copy tdmr_info and its validation 
Because the tdmr_info is generated by the kernel side, TDX should verify the
information before it is copied to the TDX memories. The main loop of the above
function iterates all TDMR passed from the host KVM side and check its validity.

```cpp
    for(uint64_t i = 0; i < num_of_tdmr_entries; i++)                           
    {                                                                           
                                                                                
        tdmr_entry.raw = tdmr_pa_array[i];                                      
        retval = shared_hpa_check_with_pwr_2_alignment(tdmr_entry, TDMR_INFO_ENTRY_PTR_ARRAY_ALIGNMENT);
        if (retval != TDX_SUCCESS)                                              
        {                                                                       
            retval = api_error_with_operand_id(retval, OPERAND_ID_RCX);         
            TDX_ERROR("TDMR entry PA is not a valid shared HPA pa=0x%llx, error=0x%llx\n", tdmr_entry.raw, retval);
            goto EXIT;                                                          
        }                                                                       
                                                                                
        tdmr_info_p = (tdmr_info_entry_t*)map_pa(tdmr_entry.raw_void, TDX_RANGE_RO);
        copy_tdmr_info_entry (tdmr_info_p, &tdmr_info_copy[i]);                 
        free_la(tdmr_info_p);                                                   
                                                                                
                                                                                
        if ((err = check_and_set_tdmrs(tdmr_info_copy, i, pamt_data_array)) != TDX_SUCCESS)
        {                                                                       
            TDX_ERROR("Check and set TDMRs failed\n");                          
            retval = err;                                                       
            goto EXIT;                                                          
        }                                                                       
        update_pamt_array(tdmr_info_copy, pamt_data_array, (uint32_t)i); // save tdmr's pamt data
    }       

```

Before validating the passed tdmr_info, it maps the tdmr_info entry, so that it 
can be accessible inside the TDX module. Recall that the passed addresses are 
physical addresses. After the mapping is established, it copies the data from 
host side to TDX module side. From now on, TDMR information can be accessible 
through the tdmr_info_copy array. 

```cpp
static api_error_type check_and_set_tdmrs(tdmr_info_entry_t tdmr_info_copy[MAX_TDMRS],
        uint64_t i, pamt_data_t pamt_data_array[])
{   
    // Check TDMR_INFO and update the internal TDMR_TABLE with TDMR, reserved areas and PAMT setup:
        
    uint64_t tdmr_base = tdmr_info_copy[i].tdmr_base;
    uint64_t prev_tdmr_base, prev_tdmr_size;
            
    // Check for integer overflow
    if (!is_valid_integer_range(tdmr_info_copy[i].tdmr_base, tdmr_info_copy[i].tdmr_size))
    {   
        TDX_ERROR("TDMR[%d]: base+size cues integer overflow\n", i);
        return api_error_with_multiple_info(TDX_INVALID_TDMR, (uint8_t)i, 0, 0, 0);
    }
        
    if (i > 0)
    {   
        prev_tdmr_base = tdmr_info_copy[i-1].tdmr_base;
        prev_tdmr_size = tdmr_info_copy[i-1].tdmr_size;
    }
        
    // TDMRs must be sorted in an ascending base address order.
    if ((i > 0) && tdmr_base < prev_tdmr_base)
    {
        TDX_ERROR("TDMR_BASE[%d]=0x%llx is smaller than TDMR_BASE[%d]=0x%llx\n",
                i, tdmr_info_copy[i].tdmr_base, i-1, tdmr_info_copy[i-1].tdmr_base);
        return api_error_with_multiple_info(TDX_NON_ORDERED_TDMR, (uint8_t)i, 0, 0, 0);
    }

    // TDMRs must not overlap with other TDMRs.
    // Check will be correct due to previous (ascension) check correctness.
    if ((i > 0) && (tdmr_base < prev_tdmr_base + prev_tdmr_size))
    {
        TDX_ERROR("TDMR[%d]: (from 0x%llx to 0x%llx) overlaps TDMR[%d] at 0x%llx\n",
                i-1, prev_tdmr_base, prev_tdmr_base + prev_tdmr_size, i, tdmr_base);
        return api_error_with_multiple_info(TDX_NON_ORDERED_TDMR, (uint8_t)i, 0, 0, 0);
    }

    api_error_type err;
    if ((err = check_tdmr_area_addresses_and_size(tdmr_info_copy, (uint32_t)i)) != TDX_SUCCESS)
    {
        return err;
    }

    if ((err = check_tdmr_reserved_areas(tdmr_info_copy, (uint32_t)i)) != TDX_SUCCESS)
    {
        return err;
    }
    if ((err = check_tdmr_pamt_areas(tdmr_info_copy, (uint32_t)i, pamt_data_array)) != TDX_SUCCESS)
    {
        return err;
    }

    if ((err = check_tdmr_available_areas(tdmr_info_copy, (uint32_t)i)) != TDX_SUCCESS)
    {
        return err;
    }
    // All checks passed for current TDMR, fill it in our module data:

    set_tdmr_info_in_global_data(tdmr_info_copy, (uint32_t)i);

    return TDX_SUCCESS;

}

```
check_and_set_tdmrs validates whether the TDMR regions are sorted ascending 
order, addresses and size has been correctly configured, etc. 


```cpp
static void set_tdmr_info_in_global_data(tdmr_info_entry_t tdmr_info_copy[MAX_TDMRS], uint32_t i)
{
    tdx_module_global_t* global_data_ptr = get_global_data();
    
    global_data_ptr->tdmr_table[i].base = tdmr_info_copy[i].tdmr_base;
    global_data_ptr->tdmr_table[i].size = tdmr_info_copy[i].tdmr_size;
    global_data_ptr->tdmr_table[i].last_initialized = global_data_ptr->tdmr_table[i].base;
    global_data_ptr->tdmr_table[i].lock = 0;
    global_data_ptr->tdmr_table[i].pamt_1g_base = tdmr_info_copy[i].pamt_1g_base;
    global_data_ptr->tdmr_table[i].pamt_2m_base = tdmr_info_copy[i].pamt_2m_base;
    global_data_ptr->tdmr_table[i].pamt_4k_base = tdmr_info_copy[i].pamt_4k_base;
    global_data_ptr->tdmr_table[i].num_of_pamt_blocks = (uint32_t)(tdmr_info_copy[i].tdmr_size / _1GB);
    
    global_data_ptr->tdmr_table[i].num_of_rsvd_areas = 0;
    for (uint32_t j = 0; j < MAX_RESERVED_AREAS; j++)
    {
        global_data_ptr->tdmr_table[i].rsvd_areas[j].offset = tdmr_info_copy[i].rsvd_areas[j].offset;
        global_data_ptr->tdmr_table[i].rsvd_areas[j].size = tdmr_info_copy[i].rsvd_areas[j].size;
    
        if (global_data_ptr->tdmr_table[i].rsvd_areas[j].size == 0)
        {
            // NULL entry is last 
            break;
        }
    
        global_data_ptr->tdmr_table[i].num_of_rsvd_areas++;
    }   
}       
```

The validated TDMR is copied to the **global_data_ptr->tdmr_table** so that the
TDMR information can be globally accessed during processing TDX operations. 
Recall that **TDMR is not enforced through specific registers**, but checked by
the TDX module (software constraint) during its runtime. Also the information of
the TDMR such as base and size of the TDMR is entirely provided by the host KVM,
but the information is copied to the TDX module during the initialization.



```cpp
_STATIC_INLINE_ void update_pamt_array (tdmr_info_entry_t*   tdmr_info_copy, pamt_data_t pamt_data_array[], uint32_t i)
{   
    pamt_data_array[i].pamt_1g_base = tdmr_info_copy[i].pamt_1g_base;
    pamt_data_array[i].pamt_1g_size = tdmr_info_copy[i].pamt_1g_size;
    pamt_data_array[i].pamt_2m_base = tdmr_info_copy[i].pamt_2m_base;
    pamt_data_array[i].pamt_2m_size = tdmr_info_copy[i].pamt_2m_size;
    pamt_data_array[i].pamt_4k_base = tdmr_info_copy[i].pamt_4k_base;
    pamt_data_array[i].pamt_4k_size = tdmr_info_copy[i].pamt_4k_size;
}   
```

After setting up the global variable for TDMR, set_tdmr_info_in_global_data, it
updates PAMT associated with the TDMR by update_pamt_array. Note that this 
information is used for verifying other TDMRs. 


## Per Package Key initialization for TDX Module
### Host KVM side
```cpp
        /* Config the key of global KeyID on all packages */
        ret = config_global_keyid();
        if (ret)
                goto out_free_pamts;

```
```cpp
static int config_global_keyid(void)
{       
        struct seamcall_ctx sc = { .fn = TDH_SYS_KEY_CONFIG };

        /*
         * Configure the key of the global KeyID on all packages by
         * calling TDH.SYS.KEY.CONFIG on all packages.
         *      
         * TDH.SYS.KEY.CONFIG may fail with entropy error (which is
         * a recoverable error).  Assume this is exceedingly rare and
         * just return error if encountered instead of retrying.
         */
        return seamcall_on_each_package_serialized(&sc);
}
```
The key initialization should be invoked per CPU package, not per core. 

### TDX Module side 
```cpp
api_error_type tdh_sys_key_config(void)
{
    bool_t tmp_global_lock_acquired = false;
    tdx_module_global_t* tdx_global_data_ptr = get_global_data();
    tdx_module_local_t* tdx_local_data_ptr = get_local_data();
    api_error_type retval = TDX_SYS_BUSY;
    ......
    // Execute PCONFIG to configure the TDX-SEAM global private HKID on the package, with a CPU-generated random key.
    // PCONFIG may fail due to and entropy error or a device busy error.
    // In this case, the VMM should retry TDHSYSKEYCONFIG.
    retval = program_mktme_keys(tdx_global_data_ptr->hkid);
    if (retval != TDX_SUCCESS)
    {
        TDX_ERROR("Failed to program MKTME keys for this package\n");
        // Clear the package configured bit
        _lock_btr_32b(&tdx_global_data_ptr->pkg_config_bitmap, tdx_local_data_ptr->lp_info.pkg);
        goto EXIT;
    }

    // Update the number of initialized packages. If this is the last one, update the system state.
    tdx_global_data_ptr->num_of_init_pkgs++;
    if (tdx_global_data_ptr->num_of_init_pkgs == tdx_global_data_ptr->num_of_pkgs)
    {
        tdx_global_data_ptr->global_state.sys_state = SYS_READY;
    }

    retval = TDX_SUCCESS;
```

It sets the MKTME key for TDX module for current CPU package. All information 
required to set MKTME key is stored in the tdx_global_data_ptr including whether
it provides the integrity, how to generate the key, the encryption algorithm &c.
Note that the hkid in the global data of the TDX module is passed from the host 
KVM when the TDH_SYS_CONFIG SEAMCALL is invoked. 


```cpp
  30 api_error_code_e program_mktme_keys(uint16_t hkid)
  31 {
......
  38         // set the command, hkid as keyid and encryption algorithm
  39         mktme_key_program.keyid_ctrl.command = MKTME_KEYID_SET_KEY_RANDOM;
  40     mktme_key_program.keyid = hkid;
  41 
  42     if (get_sysinfo_table()->mcheck_fields.tdx_without_integrity)
  43     {
  44         if (get_global_data()->plt_common_config.ia32_tme_activate.mk_tme_crypto_algs_aes_xts_256)
  45         {
  46             mktme_key_program.keyid_ctrl.enc_algo = AES_XTS_256;
  47         }
  48         else
  49         {
  50             mktme_key_program.keyid_ctrl.enc_algo = AES_XTS_128;
  51         }
  52 
  53     }
  54     else
  55     {
  56         mktme_key_program.keyid_ctrl.enc_algo = AES_XTS_128_WITH_INTEGRITY;
  57     }
  58 
  59         // Execute the PCONFIG instruction with the updated struct and return
  60         pconfig_return_code = ia32_mktme_key_program(&mktme_key_program);
```

After setting all information, **PCONFIG** instruction sets the key. Refer to 
ia32_mktme_key_program function detailed implementation.

### Check the global keyid 
global_private_hkid is the keyid for MKTME used for encryption and decryption of
memories belong to the TDX Module. Because it is passed from the host KVM, it 
should be validated whether the HKID belongs to the private HKID range. If it 
belongs to the private HKID range, then it is saved as the ephemeral key for the
TDX module. However, note that the key is not yet configured by MKTME, which
will be done by another SEAMCALL TDH_SYS_KEY_CONFIG.


## TDMR initialization
The main job of the TDH_SYS_TDMR_INIT SEAMCALL is partially initializing PATM 
blocks associated with the TDMR. Once the PAMT for each 1GB block of TDMR has 
been initialized, it marks that 1GB block as ready for use. After TDMR has been
initialized, the physical pages in 1GB TDMR becomes available for use by any 
TDX functions to create private TD page or a control structure page in 4k 
granularity (e.g., TDH.MEM.PAGE.ADD, TDH.VP.ADDCX, etc). 

### Host KVM side
For each TDMR, the VMM should execute TDH.SYS.TDMR.INIT providing TDMR start 
address as an input of the SEAMCALL. Recall that the TDMR region is initially
set by the host KVM, so it has information about all TDMR regions. 

```cpp
        /* Initialize TDMRs to complete the TDX module initialization */
        ret = init_tdmrs(tdmr_array, tdmr_num);
        if (ret)
                goto out_free_pamts;
        
        tdx_module_status = TDX_MODULE_INITIALIZED;
```

```cpp
/* Initialize all TDMRs */
static int init_tdmrs(struct tdmr_info *tdmr_array, int tdmr_num)
{
        int i;

        /*
         * Initialize TDMRs one-by-one for simplicity, though the TDX
         * architecture does allow different TDMRs to be initialized in
         * parallel on multiple CPUs.  Parallel initialization could
         * be added later when the time spent in the serialized scheme
         * becomes a real concern.
         */
        for (i = 0; i < tdmr_num; i++) {
                int ret;

                ret = init_tdmr(tdmr_array_entry(tdmr_array, i));
                if (ret)
                        return ret;
        }

        return 0;
}
```

```cpp
/* Initialize one TDMR */
static int init_tdmr(struct tdmr_info *tdmr)
{       
        u64 next;
                
        /*      
         * Initializing PAMT entries might be time-consuming (in
         * proportion to the size of the requested TDMR).  To avoid long
         * latency in one SEAMCALL, TDH.SYS.TDMR.INIT only initializes
         * an (implementation-defined) subset of PAMT entries in one
         * invocation.
         *
         * Call TDH.SYS.TDMR.INIT iteratively until all PAMT entries
         * of the requested TDMR are initialized (if next-to-initialize
         * address matches the end address of the TDMR).
         */
        do {
                struct tdx_module_output out;
                u64 ret;
                
                ret = seamcall(TDH_SYS_TDMR_INIT, tdmr->base, 0, 0, 0, &out);
                if (ret) 
                        return -EFAULT;
                /*      
                 * RDX contains 'next-to-initialize' address if
                 * TDH.SYS.TDMR.INT succeeded.
                 */
                next = out.rdx;
                /* Allow scheduling when needed */
                if (need_resched())
                        cond_resched();
        } while (next < tdmr->base + tdmr->size);

        return 0;
}

```


### TDX Module side
This SEAMCALL can be executed concurrently with adding and initializing other 
TDMRs. Also, each TDH.SYS.TDMR.INIT invocation adheres to the latency rules, 
which means it should not take more than a predefined number of clock cycles.

```cpp
api_error_type tdh_sys_tdmr_init(uint64_t tdmr_pa)
{

    tdx_module_global_t* tdx_global_data_ptr;
    tdx_module_local_t* tdx_local_data = get_local_data();
    api_error_type retval;
    bool_t lock_acquired = false;

    tdx_local_data->vmm_regs.rdx = 0ULL;

    // For each TDMR, the VMM executes a loop of SEAMCALL(TDHSYSINITTDMR),
    // providing the TDMR start address (at 1GB granularity) as an input
    if (!is_addr_aligned_pwr_of_2(tdmr_pa, _1GB) ||
        !is_pa_smaller_than_max_pa(tdmr_pa) ||
        (get_hkid_from_pa((pa_t)tdmr_pa) != 0))
    {
        retval = api_error_with_operand_id(TDX_OPERAND_INVALID, OPERAND_ID_RCX);
        goto EXIT;

    }

    tdx_global_data_ptr = get_global_data();

    //   2.  Verify that the provided TDMR start address belongs to one of the TDMRs set during TDHSYSINIT
    uint32_t tdmr_index;
    for (tdmr_index = 0; tdmr_index < tdx_global_data_ptr->num_of_tdmr_entries; tdmr_index++)
    {
        if (tdmr_pa == tdx_global_data_ptr->tdmr_table[tdmr_index].base)
        {
            break;
        }
    }
    if (tdmr_index >= tdx_global_data_ptr->num_of_tdmr_entries)
    {
        retval = api_error_with_operand_id(TDX_OPERAND_INVALID, OPERAND_ID_RCX);
        goto EXIT;
    }

    tdmr_entry_t *tdmr_entry = &tdx_global_data_ptr->tdmr_table[tdmr_index];

    if (acquire_mutex_lock(&tdmr_entry->lock) != LOCK_RET_SUCCESS)
    {
        retval = api_error_with_operand_id(TDX_OPERAND_BUSY, OPERAND_ID_RCX);
        goto EXIT;
    }

    lock_acquired = true;
```

First it checks whether a start address of the passed TDMR matches one of the 
TDMRs that have been initialized before by the TDH_SYS_CONFIG SEAMCALL. Recall
that TDH_SYS_CONFIG just verifies the TDMR and copies the TDMR content to the 
TDX module memory from Host KVM side. tdmr_entry points to the TDMR that needs 
to be initialized in this SEAMCALL invocation. 

```cpp
    ......
    //   3.  Retrieves the TDMR’s next-to-initialize address from the internal TDMR data structure.
    //       If the next-to-initialize address is higher than the address to the last byte of the TDMR, there’s nothing to do.
    //       If successful, the function does the following:
    if (tdmr_entry->last_initialized >= (tdmr_entry->base + tdmr_entry->size))
    {
        retval = TDX_TDMR_ALREADY_INITIALIZED;
        goto EXIT;
    }

    //   4.  Initialize an (implementation defined) number of PAMT entries.
    //        The maximum number of PAMT entries to be initialized is set to avoid latency issues.
    //   5.  If the PAMT for a 1GB block of TDMR has been fully initialized, mark that 1GB block as ready for use.
    //        This means that 4KB pages in this 1GB block may be converted to private pages, e.g., by TDCALL(TDHMEMPAGEADD).
    //        This can be done concurrently with initializing other TDMRs.

    pamt_block_t pamt_block;
    pamt_block.pamt_1gb_p = (pamt_entry_t*) (tdmr_entry->pamt_1g_base
            + ((tdmr_entry->last_initialized - tdmr_entry->base) / _1GB * sizeof(pamt_entry_t)));
    pamt_block.pamt_2mb_p = (pamt_entry_t*) (tdmr_entry->pamt_2m_base
            + ((tdmr_entry->last_initialized - tdmr_entry->base) / _2MB * sizeof(pamt_entry_t)));
    pamt_block.pamt_4kb_p = (pamt_entry_t*) (tdmr_entry->pamt_4k_base
            + ((tdmr_entry->last_initialized - tdmr_entry->base) / _4KB * sizeof(pamt_entry_t)));

    pamt_init(&pamt_block, TDMR_4K_PAMT_INIT_COUNT, tdmr_entry);

    //   6.  Store the updated next-to-initialize address in the internal TDMR data structure.
    tdmr_entry->last_initialized += (TDMR_4K_PAMT_INIT_COUNT * _4KB);
            
    //   7.  The returned next-to-initialize address is always rounded down to 1GB, so VMM won’t attempt to use a 1GB block that is not fully initialized.
    tdx_local_data->vmm_regs.rdx = tdmr_entry->last_initialized & ~(_1GB - 1);
    
    retval = TDX_SUCCESS;
        
    EXIT:
    
    if (lock_acquired)
    {
        release_mutex_lock(&tdx_global_data_ptr->tdmr_table[tdmr_index].lock);
    }
    
    return retval;
    }   
```

It might not initialize entire PAMT associated with one TDMR at once because of
latency issues. Therefore, the base addresses of each level of PAMT that needs 
to be initialized in this invocation should be calculated based on the last 
initialized addresses base and last addresses. 

```cpp
168 void pamt_init(pamt_block_t* pamt_block, uint64_t num_4k_entries, tdmr_entry_t *tdmr_entry)
169 {   
170     uint64_t start_pamt_4k_p = (uint64_t)pamt_block->pamt_4kb_p;
171     uint64_t end_pamt_4k_p = start_pamt_4k_p + (num_4k_entries * (uint64_t)sizeof(pamt_entry_t));
172     
173     pamt_4kb_init(pamt_block, num_4k_entries, tdmr_entry);
174     pamt_nodes_init(start_pamt_4k_p, end_pamt_4k_p, pamt_block->pamt_2mb_p, PAMT_4K_ENTRIES_IN_2MB, tdmr_entry);
175     pamt_nodes_init(start_pamt_4k_p, end_pamt_4k_p, pamt_block->pamt_1gb_p, PAMT_4K_ENTRIES_IN_1GB, tdmr_entry);
176 }  
```

It requires different initialization for PAMT correspodning to its level. For
leaf, it invokes pamt_4kb_init, and for non-leafs, it invokes pamt_nodes_init. 

```cpp
_STATIC_INLINE_ void pamt_4kb_init(pamt_block_t* pamt_block, uint64_t num_4k_entries, tdmr_entry_t *tdmr_entry)
{
    pamt_entry_t* pamt_entry = NULL;
    uint64_t current_4k_page_idx = ((uint64_t)pamt_block->pamt_4kb_p - tdmr_entry->pamt_4k_base)
                                    / sizeof(pamt_entry_t);
    uint64_t page_offset;
    uint32_t last_rsdv_idx = 0;
    
    // PAMT_CHILD_ENTRIES pamt entries take more than 1 page size, this is why
    // we need to do a new map each time we reach new page in the entries array
    // Since we work with chunks of PAMT_CHILD_ENTRIES entries it time,
    // the start address is always aligned on 4K page
    uint32_t pamt_entries_in_page = TDX_PAGE_SIZE_IN_BYTES / sizeof(pamt_entry_t);
    uint32_t pamt_pages = (uint32_t)(num_4k_entries / pamt_entries_in_page);
    
    pamt_entry_t* pamt_entry_start = pamt_block->pamt_4kb_p;
    tdx_sanity_check(((uint64_t)pamt_entry_start % TDX_PAGE_SIZE_IN_BYTES) == 0,
            SCEC_PAMT_MANAGER_SOURCE, 11);
    for (uint32_t i = 0; i < pamt_pages; i++)
    {
        pamt_entry = map_pa_with_global_hkid(
                &pamt_entry_start[pamt_entries_in_page * i], TDX_RANGE_RW);
        // create a cache aligned, cache sized chunk and fill it with 'val'
        ALIGN(MOVDIR64_CHUNK_SIZE) pamt_entry_t chunk[PAMT_4K_ENTRIES_IN_CACHE];
        basic_memset((uint64_t)chunk, PAMT_4K_ENTRIES_IN_CACHE*sizeof(pamt_entry_t), 0 , PAMT_4K_ENTRIES_IN_CACHE*sizeof(pamt_entry_t));
        for (uint32_t j = 0; j < pamt_entries_in_page; j++, current_4k_page_idx++)
        {
            page_offset = current_4k_page_idx * TDX_PAGE_SIZE_IN_BYTES;
            if (is_page_reserved(page_offset, tdmr_entry, &last_rsdv_idx))
            {
                chunk[j%PAMT_4K_ENTRIES_IN_CACHE].pt = PT_RSVD;
            }
            else
            {
                chunk[j%PAMT_4K_ENTRIES_IN_CACHE].pt = PT_NDA;
                last_rsdv_idx = 0;
            }
            if ((j+1)%PAMT_4K_ENTRIES_IN_CACHE == 0)
            {
                fill_cachelines_no_sfence((void*)&(pamt_entry[j-3]), (uint8_t*)chunk, 1);
            }
        }
        mfence();
        free_la(pamt_entry);
    }
}
```

The number of 4K PAMT pages that can be initialized at once is set by constant 
TDMR_4K_PAMT_INIT_COUNT (i.e., 1KB PAMT entries in current version) to satisfy 
latency constraint. Based on how many PAMT entries can exist in 4K page, the 
number of PAMT pages that should be initialized will be determined. It iterates
each page and first map the PAMT page. Recall that PAMTs are located at the host
KVM controlled physical memory pages. However, to protect the PAMTs from the 
possibly malicious VMM, it maps the physical addresses of the PAMTs with HKID 
of the TDX module. As a result, the VMM cannot read/write the plain text of the 
PAMTs because HKID used for encryption belongs to the private HKID space. After 
the mapping, based on whether it is reserved or not, each PAMT 4K page's type is 
set.

```cpp
_STATIC_INLINE_ void pamt_nodes_init(uint64_t start_pamt_4k_p, uint64_t end_pamt_4k_p,
        pamt_entry_t* nodes_array, uint64_t entries_in_node, tdmr_entry_t *tdmr_entry)
{
    pamt_entry_t* pamt_entry;

    uint64_t entries_start = (start_pamt_4k_p - tdmr_entry->pamt_4k_base) / (entries_in_node * (uint64_t)sizeof(pamt_entry_t));
    uint64_t entries_end   = (end_pamt_4k_p - tdmr_entry->pamt_4k_base) / (entries_in_node * (uint64_t)sizeof(pamt_entry_t));

    uint32_t i = 0;
    while ((entries_end - (uint64_t)i) > entries_start)
    {
        void* entry_p = &nodes_array[i];
        pamt_entry = map_pa_with_global_hkid(entry_p, TDX_RANGE_RW);
        if (is_cacheline_aligned(entry_p))
        {
            zero_cacheline(pamt_entry);
        }
        pamt_entry->pt = PT_NDA;
    
        free_la(pamt_entry);
        i++;
    }
}   
```

Note that the start and end addresses of the pamt_4k (1st and 2nd params) is 
calculated based on how many 4k PAMTs can be initialized in this SEAMCALL. 
Also, it passes entries_in_node param which is the size of each level of PAMT in
4K PAMT pages, so that the number of PAMT entries that needs to be initialized 
in non-leaf levels can be determined. Rest of the code is similar to the code
for leaf PAMT initialization. Now all other SEAMCALLS are available!!

## Map physical address in TDX module 
Most of the addresses passed from the host KVM to TDX module are physical addr
belong to CMR, which might not be converted to the TDX private pages yet. 
Therefore, to securely accesses those memories, it should map the physical pages
to its private pages beforehand. 

```cpp
typedef enum
{       
    TDX_RANGE_RO   = 0,
    TDX_RANGE_RW   = 1
} mapping_type_t;

void* map_pa(void* pa, mapping_type_t mapping_type)
{   
    return map_pa_with_memtype(pa, mapping_type, true);
}   
```

```cpp
static void* map_pa_with_memtype(void* pa, mapping_type_t mapping_type, bool_t is_wb_memtype)
{   
    keyhole_state_t* keyhole_state = &get_local_data()->keyhole_state;
    bool_t is_writable = (mapping_type == TDX_RANGE_RW) ? true : false;
    
    // Search the requested PA first, if it's mapped or cached
    uint16_t keyhole_idx = hash_table_find_entry((uint64_t)pa, is_writable, is_wb_memtype, NULL);
    
#ifdef DEBUG 
    // Increment the total ref count and check for overflow
    keyhole_state->total_ref_count += 1;
    tdx_debug_assert(keyhole_state->total_ref_count != 0); 
#endif  
    
    // Requested PA is already mapped/cached
    if (keyhole_idx != UNDEFINED_IDX)
    {   
        tdx_debug_assert(keyhole_idx < MAX_KEYHOLE_PER_LP);
        // If the relevant keyhole is marked for removal, remove it from the LRU cache list
        // and make it "mapped"
        if (keyhole_state->keyhole_array[keyhole_idx].state == KH_ENTRY_CAN_BE_REMOVED)
        {
            lru_cache_remove_entry(keyhole_idx);
            keyhole_state->keyhole_array[keyhole_idx].state = (uint8_t)KH_ENTRY_MAPPED;
        }
        keyhole_state->keyhole_array[keyhole_idx].ref_count += 1;

        // Protection against speculative attacks on sensitive physical addresses
        lfence();

        // In any case, both MAPPED and CAN_BE_REMOVED - return the existing LA to the user
        return (void*)(la_from_keyhole_idx(keyhole_idx) | PG_OFFSET((uint64_t)pa));
    }

    // If it's not mapped, take the entry from LRU tail
    // If there are any free entries, they will be first from tail in the LRU list
    keyhole_idx = keyhole_state->lru_tail;

    // Check if there any available keyholes left, otherwise - kill the module
    tdx_sanity_check(keyhole_idx != UNDEFINED_IDX, SCEC_KEYHOLE_MANAGER_SOURCE, 0);

    keyhole_entry_t* target_keyhole = &keyhole_state->keyhole_array[keyhole_idx];

    uint64_t la = la_from_keyhole_idx(keyhole_idx) | PG_OFFSET((uint64_t)pa);

    // Remove the entry from the LRU list - valid for both FREE and CAN_BE_REMOVED
    lru_cache_remove_entry(keyhole_idx);

    // If a cached entry is being reused:
    bool_t flush = (target_keyhole->state == KH_ENTRY_CAN_BE_REMOVED);

    // Remove it from LRU list, remove it from the search hash table, and flush TLB
    if (flush)
    {
        hash_table_remove_entry(target_keyhole->mapped_pa, target_keyhole->is_writable,
                                target_keyhole->is_wb_memtype);
    }

    // Update the entry info, insert it to the search hash table, and fill the actual PTE
    target_keyhole->state = KH_ENTRY_MAPPED;
    target_keyhole->mapped_pa = PG_START((uint64_t)pa);
    target_keyhole->is_writable = is_writable;
    target_keyhole->is_wb_memtype = is_wb_memtype;
    target_keyhole->ref_count += 1;

    hash_table_insert_entry((uint64_t)pa, keyhole_idx);
    fill_keyhole_pte(keyhole_idx, (uint64_t)pa, is_writable, is_wb_memtype);

    // Flush the TLB for a reused entry - ***AFTER*** the PTE was updated
    // If INVLPG is done before the PTE is updated - the TLB entry may not be flushed properly
    if (flush)
    {
        ia32_invalidate_tlb_entries(la);
    }

    // Protection against speculative attacks on sensitive physical addresses
    lfence();

    return (void*)la;
}
```

**Each logical processor** has keyhole state that manages keyhole entries 
(keyhole_entry_t) holding physical to linear PTE mappings. Why we need keyhole..?

```cpp
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


```cpp
/** 
 * @struct kot_t
 *  
 * @brief KOT = Key Ownership Table
 *  
 * KOT is used to manage HKIDs state and ownership by TDs
 */ 
typedef struct kot_s
{
    sharex_lock_t lock; /**< shared exclusve lock to access the kot */
    /**
     * A table of MAX_HKIDS entries, indexed by HKID
     */
    kot_entry_t entries[MAX_HKIDS];
} kot_t;
```


### Other interfaces
```cpp
_STATIC_INLINE_ void* map_pa_with_global_hkid(void* pa, mapping_type_t mapping_type)
{       
    uint16_t tdx_global_hkid = get_global_data()->hkid;
    return map_pa_with_hkid(pa, tdx_global_hkid, mapping_type);
}       

_STATIC_INLINE_ void* map_pa_with_hkid(void* pa, uint16_t hkid, mapping_type_t mapping_type) 
{   
    pa_t temp_pa = {.raw_void = pa};
    pa_t pa_with_hkid = set_hkid_to_pa(temp_pa, hkid);
    return map_pa((void*) pa_with_hkid.raw, mapping_type);
}   
        
```


<!--

[[/assets/img/TDX//tdcs-mm-alloc.png]]

[[/assets/img/TDX//tdmr-resource-reclam.png]]
-->















