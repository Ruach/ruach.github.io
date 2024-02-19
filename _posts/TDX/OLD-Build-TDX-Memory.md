### Build tmem 

### Build TDMR range based on tmem
```cpp
/*
 * Structure to describe an address range, referred as TDMR range, which meets
 * TDMR's 1G alignment.  It is used to assist constructing TDMRs.  Final TDMRs
 * are generated on basis of TDMR range, meaning one TDMR range can have one or
 * multiple TDMRs, but one TDMR cannot cross two TDMR ranges.
 *
 * @start_1g and @end_1g are 1G aligned.  @first_tmb and @last_tmb are the first
 * and last TDX memory block that the TDMR range covers.  Note both @first_tmb
 * and @last_tmb may only have part of it covered by the TDMR range.
 */
struct tdmr_range {
        struct list_head list;
        phys_addr_t start_1g;
        phys_addr_t end_1g;
        int nid;
        struct tdx_memblock *first_tmb;
        struct tdx_memblock *last_tmb;
};
```


### Build TMDRs based on TDMR range 
distribute_tdmrs_across_tdmr_ranges, tdmr_range_distribute_tdmrs


### Setup PAMTs for TDMRs
```cpp
 887  * Third step of constructing final TDMRs:
 888  *
 889  * Allocate PAMTs for distributed TDMRs in previous step, and set up PAMT info
 890  * to TDMR_INFO array, which is used by TDX module.  Allocating PAMTs must be
 891  * done after distributing all TDMRs on final TDX memory, since PAMT size
 892  * depends on this.
 893  */
 894 static int __init setup_pamts_across_tdmrs(struct tdx_memory *tmem,
 895                 int pamt_entry_sz_array[TDX_PG_MAX],
 896                 struct tdmr_info *tdmr_info_array)
 897 {
 898         int ret;
 899 
 900         tmem_setup_pamt_candidates(tmem);
 901 
 902         ret = tmem_alloc_pamt_pools(tmem, pamt_entry_sz_array);
 903         if (ret)
 904                 return ret;
 905 
 906         tmem_setup_pamts(tmem, pamt_entry_sz_array);
 907 
 908         tmem_setup_tdmr_info_pamts(tmem, pamt_entry_sz_array,

```



### Filling up reserved area within the TDMRs
```cpp
/*
 * Last step of constructing final TDMRs:
 *
 * Put TDX memory block holes and PAMTs into reserved areas of TDMRs.
 */
static int __init fillup_reserved_areas_across_tdmrs(struct tdx_memory *tmem,
                struct tdmr_info *tdmr_info_array, int max_rsvd_area_num)
{
        int i, ret;

        for (i = 0; i < tmem->tdmr_num; i++) {
                ret = fillup_tdmr_reserved_areas(tmem, &tdmr_info_array[i],
                                max_rsvd_area_num);
                if (ret)
                        return ret;
        }

        return 0;
}
```


```cpp
1108 /*
1109  * Fill up TDMR's reserved areas with holes between TDX memory blocks, and
1110  * PAMTs that are within TDMR address range, in ascending order.  @tdmr's
1111  * base, size must already been set.
1112  *
1113  * Return 0 upon success, or -E2BIG if maximum reserved area is reached, or
1114  * other fatal errors.
1115  */
1116 static int __init fillup_tdmr_reserved_areas(struct tdx_memory *tmem,
1117                 struct tdmr_info *tdmr_info, int max_rsvd_area_num)
1118 {
1119         struct tdx_memblock *tmb, *prev_tmb;
1120         struct rsvd_pamt_ctx pamt_ctx;
1121         struct rsvd_pamt *pamt;
1122         unsigned long tdmr_start_pfn, tdmr_end_pfn;
1123         u64 tdmr_start, tdmr_end;
1124         u64 addr, size;
1125         int rsvd_idx = 0;
1126         int ret = 0;
1127 
1128         tdmr_start = tdmr_info->base;
1129         tdmr_end = tdmr_info->base + tdmr_info->size;
1130         tdmr_start_pfn = tdmr_start >> PAGE_SHIFT;
1131         tdmr_end_pfn = tdmr_end >> PAGE_SHIFT;
1132 
1133         /*
1134          * Prepare all the PAMT ranges that fall into TDMR's range.  Those
1135          * PAMT ranges need to be put into TDMR's reserved areas.
1136          */
1137         ret = prepare_rsvd_pamt_ctx(tmem, tdmr_start_pfn, tdmr_end_pfn,
1138                         &pamt_ctx);
1139         if (ret)
1140                 goto out;
1141 
1142         /* Find the first memory block that has overlap with TDMR */
1143         list_for_each_entry(tmb, &tmem->tmb_list, list)
1144                 if (tmb->end_pfn > tdmr_start_pfn)
1145                         break;
1146 
1147         /* Unable to find? Something is wrong here. */
1148         if (WARN_ON_ONCE(list_entry_is_head(tmb, &tmem->tmb_list, list))) {
1149                 ret = -EINVAL;
1150                 goto out;
1151         }
1152 
1153         /*
1154          * If memory block's start is beyond TDMR start, put [tdmr_start,
1155          * tmb_start] into reserved area.
1156          */
1157         if (tmb->start_pfn > tdmr_start_pfn) {
1158                 addr = tdmr_start;
1159                 size = tmb->start_pfn > tdmr_end_pfn ? (tdmr_end - tdmr_start) :
1160                         ((tmb->start_pfn << PAGE_SHIFT) - tdmr_start);
1161                 if (fillup_tdmr_reserved_area_with_pamt(tdmr_info, &rsvd_idx,
1162                                         addr, size, &pamt_ctx,
1163                                         max_rsvd_area_num)) {
1164                         ret = -E2BIG;
1165                         goto out;
1166                 }
1167         }
1168 
1169         /* If this memory block has already covered entire TDMR, it's done. */
1170         if (tmb->end_pfn >= tdmr_end_pfn)
1171                 goto done;
1172 
1173         /*
1174          * Keep current block as previous block, and continue to walk through
1175          * all blocks to check whether there's any holes between them within
1176          * TDMR, and if there's any, put to reserved areas.
1177          */
1178         prev_tmb = tmb;
1179         list_for_each_entry_continue(tmb, &tmem->tmb_list, list) {
1180                 /*
1181                  * If next block's start is beyond TDMR range, then the loop is
1182                  * done, and only need to put [prev_tr->end, tdmr_end] to
1183                  * reserved area. Just break out to handle.
1184                  */
1185                 if (tmb->start_pfn >= tdmr_end_pfn)
1186                         break;
1187 
1188                 /*
1189                  * Otherwise put hole between previous block and current one
1190                  * into reserved area.
1191                  */
1192                 addr = prev_tmb->end_pfn << PAGE_SHIFT;
1193                 size = (tmb->start_pfn << PAGE_SHIFT) - addr;
1194                 if (fillup_tdmr_reserved_area_with_pamt(tdmr_info, &rsvd_idx,
1195                                         addr, size, &pamt_ctx,
1196                                         max_rsvd_area_num)) {
1197                         ret = -E2BIG;
1198                         goto out;
1199                 }
1200 
1201                 /* Update previous block and keep looping */
1202                 prev_tmb = tmb;
1203         }
1204 
1205         /*
1206          * When above loop never happened (when memory block is the last one),
1207          * or when it hit memory block's start is beyond TDMR range, add
1208          * [prev_tmb->end, tdmr_end] to reserved area, when former is less.
1209          */
1210         if (prev_tmb->end_pfn >= tdmr_end_pfn)
1211                 goto done;
1212 
1213         addr = prev_tmb->end_pfn << PAGE_SHIFT;
1214         size = tdmr_end - addr;
1215         if (fillup_tdmr_reserved_area_with_pamt(tdmr_info, &rsvd_idx, addr,
1216                                 size, &pamt_ctx, max_rsvd_area_num)) {
1217                 ret = -E2BIG;
1218                 goto out;
1219         }
1220 
1221 done:
1222         /* PAMTs may not have been handled, handle them here */
1223         list_for_each_entry(pamt, &pamt_ctx.pamt_list, list) {
1224                 if (pamt->inserted)
1225                         continue;
1226                 if (fillup_tdmr_reserved_area(tdmr_info, &rsvd_idx, pamt->base,
1227                                         pamt->sz, max_rsvd_area_num)) {
1228                         ret = -E2BIG;
1229                         goto out;
1230                 }
1231         }
1232 out:
1233         return ret;
1234 }
```


### Locate biggest tmb residing tdmr for PAMT 
```cpp
 669 /*
 670  * First step of allocating PAMTs for TDMRs:
 671  *
 672  * Find one TDX memory block for each TDMR as candidate for PAMT allocation.
 673  * After this, each TDMR will have one block for PAMT allocation, but the same
 674  * block may be used by multiple TDMRs for PAMT allocation.
 675  */
 676 static void __init tmem_setup_pamt_candidates(struct tdx_memory *tmem)
 677 {
 678         int i;
 679 
 680         for (i = 0; i < tmem->tdmr_num; i++)
 681                 tdmr_setup_pamt_candidate(tmem, &tmem->tdmr_array[i]);
 682 }
```


```cpp
 619 /***************************** PAMT allocation *****************************/
 620 
 621 /*
 622  * For given TDMR, among all TDX memory blocks (full or part) that are within
 623  * the TDMR, find one TDX memory block as candidate for PAMT allocation.  So
 624  * far just find the largest block as candidate.
 625  */
 626 static void __init tdmr_setup_pamt_candidate(struct tdx_memory *tmem,
 627                 struct tdx_tdmr *tdmr)
 628 {
 629         struct tdx_memblock *tmb, *largest_tmb = NULL;
 630         unsigned long largest_tmb_pfn = 0;
 631 
 632         list_for_each_entry(tmb, &tmem->tmb_list, list) {
 633                 unsigned long start_pfn = tmb->start_pfn;
 634                 unsigned long end_pfn = tmb->end_pfn;
 635                 unsigned long tmb_pfn;
 636 
 637                 /* Skip those fully below @tdmr */
 638                 if (TDX_MEMBLOCK_TDMR_END(tmb) <= tdmr->start_1g)
 639                         continue;
 640 
 641                 /* Skip those fully above @tdmr */
 642                 if (TDX_MEMBLOCK_TDMR_START(tmb) >= tdmr->end_1g)
 643                         break;
 644 
 645                 /* Only calculate size of the part that is within TDMR */
 646                 if (start_pfn < (tdmr->start_1g >> PAGE_SHIFT))
 647                         start_pfn = (tdmr->start_1g >> PAGE_SHIFT);
 648                 if (end_pfn > (tdmr->end_1g >> PAGE_SHIFT))
 649                         end_pfn = (tdmr->end_1g >> PAGE_SHIFT);
 650 
 651                 tmb_pfn = end_pfn - start_pfn;
 652                 if (largest_tmb_pfn < tmb_pfn) {
 653                         largest_tmb_pfn = tmb_pfn;
 654                         largest_tmb = tmb;
 655                 }
 656         }
 657 
 658         /*
 659          * There must be at least one block (or part of it) within one TDMR,
 660          * otherwise it is a bug.
 661          */
 662         if (WARN_ON_ONCE(!largest_tmb))
 663                 largest_tmb = list_first_entry(&tmem->tmb_list,
 664                                 struct tdx_memblock, list);
 665 
 666         tdmr->tmb = largest_tmb;
 667 }
```

Note that the tmb pointer of the tdmr points to the largest tmb block within 
that TDMR.


### 
```cpp
 773 /*
 774  * Second step of allocating PAMTs for TDMRs:
 776  * Allocate one PAMT pool for all TDMRs that use the same TDX memory block for
 777  * PAMT allocation.  PAMT for each TDMR will later be divided from the pool.
 778  * This helps to minimize number of PAMTs and reduce consumption of TDMR's
 779  * reserved areas for PAMTs.
 780  */
 781 static int __init tmem_alloc_pamt_pools(struct tdx_memory *tmem,
 782                 int pamt_entry_sz_array[TDX_PG_MAX])
 783 {
 784         struct tdx_memblock *tmb;
 785 
 786         list_for_each_entry(tmb, &tmem->tmb_list, list) {
 787                 int ret;
 788 
 789                 ret = tmb_alloc_pamt_pool(tmem, tmb, pamt_entry_sz_array);
 790                 /*
 791                  * Just return in case of error.  PAMTs are freed in
 792                  * tdx_memory_destroy() before freeing any TDX memory
 793                  * blocks.
 794                  */
 795                 if (ret)
 796                         return ret;
 797         }
 798 
 799         return 0;
 800 }
```

```cpp
 718 /* Allocate one PAMT pool for all TDMRs that use given TDX memory block. */
 719 static int __init tmb_alloc_pamt_pool(struct tdx_memory *tmem,
 720                 struct tdx_memblock *tmb, int pamt_entry_sz_array[TDX_PG_MAX])
 721 {
 722         struct tdx_pamt *pamt;
 723         unsigned long pamt_pfn, pamt_sz;
 724         int i;
 725 
 726         /* Get all TDMRs that use the same @tmb as PAMT allocation */
 727         pamt_sz = 0;
 728         for (i = 0; i < tmem->tdmr_num; i++)  {
 729                 struct tdx_tdmr *tdmr = &tmem->tdmr_array[i];
 730 
 731                 if (tdmr->tmb != tmb)
 732                         continue;
 733 
 734                 pamt_sz += tdmr_get_pamt_sz(tdmr, pamt_entry_sz_array);
 735         }
 736 
 737         /*
 738          * If one TDMR range has multiple TDX memory blocks, it's possible
 739          * all TDMRs within this range use one block as PAMT candidate, in
 740          * which case other blocks won't be PAMT candidate for any TDMR.
 741          * Just skip in this case.
 742          */
 743         if (!pamt_sz)
 744                 return 0;
 745 
 746         pamt = kzalloc(sizeof(*pamt), GFP_KERNEL);
 747         if (!pamt)
 748                 return -ENOMEM;
 749 
 750         pamt_pfn = tmb->ops->pamt_alloc(tmb, pamt_sz >> PAGE_SHIFT);
 751         if (!pamt_pfn) {
 752                 kfree(pamt);
 753                 return -ENOMEM;
 754         }
 755 
 756         INIT_LIST_HEAD(&pamt->list);
 757         pamt->pamt_pfn = pamt_pfn;
 758         pamt->total_pages = pamt_sz >> PAGE_SHIFT;
 759         pamt->free_pages = pamt_sz >> PAGE_SHIFT;
 760         /* In order to use tmb->ops->pamt_free() */
 761         pamt->tmb = tmb;
 762         /* Setup TDX memory block's PAMT pool */
 763         tmb->pamt = pamt;
 764         /*
 765          * Add PAMT to @tmem->pamt_list, so they can be easily freed before
 766          * freeing any TDX memory block.
 767          */
 768         list_add_tail(&pamt->list, &tmem->pamt_list);
 769 
 770         return 0;
 771 }
```

It first locates TDMR that utilize the tmb (passed as parameter) as the PAMT. 
Because one PAMT can cover multiple TDX memory regions, multiple TDMR can 
utilize the same PAMT, which means that multiple TDMR's PAMT location (tdmr->tmb)
can match with the tmb. The reason of locating all TMDRs matching tmb is that it
needs to calculate the size of PAMT (pamt_sz). After that, it allocates memory 
for PAMT and assign the PAMT to tmb. As a result, we can locate the PAMT 
structure managing particular tmb. 

```cpp
 827 /*
 828  * Third step of allocating PAMTs for TDMRs:
 829  *
 830  * Set up PAMTs for all TDMRs by dividing PAMTs from PAMT pools.
 831  */
 832 static void __init tmem_setup_pamts(struct tdx_memory *tmem,
 833                 int pamt_entry_sz_array[TDX_PG_MAX])
 834 {
 835         int i;
 836 
 837         for (i = 0; i < tmem->tdmr_num; i++)
 838                 tdmr_setup_pamt(&tmem->tdmr_array[i], pamt_entry_sz_array);
 839 }
```

```cpp
 817 /* Set up PAMT for given TDMR from PAMT pool. */
 818 static void __init tdmr_setup_pamt(struct tdx_tdmr *tdmr,
 819                 int pamt_entry_sz_array[TDX_PG_MAX])
 820 {
 821         unsigned long npages =
 822                 tdmr_get_pamt_sz(tdmr, pamt_entry_sz_array) >> PAGE_SHIFT;
 823 
 824         tdmr->pamt_pfn = pamt_pool_alloc(tdmr->tmb->pamt, npages);
 825 }
```

Memory pool for PAMT has been allocated, but it has not been distributed to the
yet. Here, pamt_pool_alloc actually assigns part of the PAMT memory to the TDMR. 


### Set TDMR_INFO structure
Note that tdmr_info_array contains entire final information regarding TDMR. This
array is the **tdmr_info** variable.

```cpp
 869 /*
 870  * Final step of allocating PAMTs for TDMRs:
 871  *
 872  * Set up PAMT info for all TDMR_INFO structures.
 873  */
 874 static void __init tmem_setup_tdmr_info_pamts(struct tdx_memory *tmem,
 875                 int pamt_entry_sz_array[TDX_PG_MAX],
 876                 struct tdmr_info *tdmr_info_array)
 877 {
 878         int i;
 879 
 880         for (i = 0; i < tmem->tdmr_num; i++)
 881                 tdmr_info_setup_pamt(&tmem->tdmr_array[i],
 882                                 pamt_entry_sz_array,
 883                                 &tdmr_info_array[i]);
 884 }
```

```cpp
 841 /* Set up PAMT info in TDMR_INFO, which is used by TDX module. */
 842 static void __init tdmr_info_setup_pamt(struct tdx_tdmr *tdmr,
 843                 int pamt_entry_sz_array[TDX_PG_MAX],
 844                 struct tdmr_info *tdmr_info)
 845 {
 846         unsigned long pamt_base_pgsz = tdmr->pamt_pfn << PAGE_SHIFT;
 847         unsigned long pamt_base[TDX_PG_MAX];
 848         unsigned long pamt_sz[TDX_PG_MAX];
 849         enum tdx_page_sz pgsz;
 850 
 851         for (pgsz = TDX_PG_4K; pgsz < TDX_PG_MAX; pgsz++) {
 852                 unsigned long sz = tdmr_range_to_pamt_sz(tdmr->start_1g,
 853                                 tdmr->end_1g, pgsz, pamt_entry_sz_array[pgsz]);
 854 
 855                 pamt_base[pgsz] = pamt_base_pgsz;
 856                 pamt_sz[pgsz] = sz;
 857 
 858                 pamt_base_pgsz += sz;
 859         }
 860 
 861         tdmr_info->pamt_4k_base = pamt_base[TDX_PG_4K];
 862         tdmr_info->pamt_4k_size = pamt_sz[TDX_PG_4K];
 863         tdmr_info->pamt_2m_base = pamt_base[TDX_PG_2M];
 864         tdmr_info->pamt_2m_size = pamt_sz[TDX_PG_2M];
 865         tdmr_info->pamt_1g_base = pamt_base[TDX_PG_1G];
 866         tdmr_info->pamt_1g_size = pamt_sz[TDX_PG_1G];
 867 }
```

## Final initialization of TDX memory
```cpp
1196 /*
1197  * __tdx_init_module - finial initialization of TDX module so that it can be
1198  *                     workable.
1199  */
1200 static int __tdx_init_module(void)
1201 {
1202         u64 *tdmr_addrs;
1203         u64 err;
1204         int ret = 0;
1205         int i;
1206 
1207         /*
1208          * tdmr_addrs must be aligned to TDX_TDMR_ADDR_ALIGNMENT(512).
1209          * kmalloc() returns size-aligned when size is power of 2.
1210          */
1211         BUILD_BUG_ON(!is_power_of_2(sizeof(*tdmr_addrs) * TDX_MAX_NR_TDMRS));
1212         BUILD_BUG_ON(!IS_ALIGNED(sizeof(*tdmr_addrs) * TDX_MAX_NR_TDMRS,
1213                                  TDX_TDMR_ADDR_ALIGNMENT));
1214         tdmr_addrs = kmalloc(sizeof(*tdmr_addrs) * TDX_MAX_NR_TDMRS, GFP_KERNEL);
1215         if (!tdmr_addrs)
1216                 return -ENOMEM;
1217 
1218         for (i = 0; i < tdx_nr_tdmrs; i++)
1219                 tdmr_addrs[i] = __pa(&tdmr_info[i]);
1220 
1221         /*
1222          * tdh_sys_tdmr_config() calls TDH.SYS.CONFIG to tell TDX module about
1223          * TDMRs, PAMTs and HKID for TDX module to use.  Use the first keyID as
1224          * TDX-SEAM's global key.
1225          */
1226         err = tdh_sys_tdmr_config(__pa(tdmr_addrs), tdx_nr_tdmrs,
1227                                   tdx_keyids_start);
1228         if (WARN_ON_ONCE(err)) {
1229                 pr_seamcall_error(SEAMCALL_TDH_SYS_CONFIG, "TDH_SYS_CONFIG",
1230                                   err, NULL);
1231                 ret = -EIO;
1232                 goto out;
1233         }
```


### TDH.SYS.CONFIG (TDX module side)
```cpp
721 api_error_type tdh_sys_config(uint64_t tdmr_info_array_pa,
722                              uint64_t num_of_tdmr_entries,
723                              hkid_api_input_t global_private_hkid)
724 {   
725     // Temporary Variables 
726     
727     tdmr_info_entry_t*   tdmr_info_p;   // Pointer to TDMR info
728     tdmr_info_entry_t*   tdmr_info_copy;// Pointer to TDMR info array
729     bool_t               tdmr_info_p_init = false;
730     pa_t                 tdmr_info_pa = {.raw = tdmr_info_array_pa};  // Physical address of an array of physical addresses of the TDMR info structure
731     uint64_t*            tdmr_pa_array = NULL; // Pointer to an array of physical addresses of the TDMR info structure
732     uint16_t             hkid = global_private_hkid.hkid;
733     bool_t               global_lock_acquired = false;
734     tdx_module_global_t* tdx_global_data_ptr = get_global_data();
```
The first parameter tdmr_info_array_pa is the array containing physical addresses of the tdmr_info
maintained by the kernel. It has been passed as a physical addresses, it should be remapped by the 
TDX module before it is accessed to get the TDMR information. After mapping physical addresses, it 
accesses the data through **tmdr_info_entry_t** struct pointer. TDMR information is copied to the 
tdmr_info_copy field of the tdx_global_data_ptr. 

```cpp
807 /**
808  * @struct tdmr_info_entry_t
809  *
810  * @brief TDMR_INFO provides information about a TDMR and its associated PAMT
811  *
812  * An array of TDMR_INFO entries is passed as input to SEAMCALL(TDHSYSCONFIG) leaf function.
813  *
814  * - The TDMRs must be sorted from the lowest base address to the highest base address,
815  *   and must not overlap with each other.
816  *
817  * - Within each TDMR entry, all reserved areas must be sorted from the lowest offset to the highest offset,
818  *   and must not overlap with each other.
819  *
820  * - All TDMRs and PAMTs must be contained within CMRs.
821  *
822  * - A PAMT area must not overlap with another PAMT area (associated with any TDMR), and must not
823  *   overlap with non-reserved areas of any TDMR. PAMT areas may reside within reserved areas of TDMRs.
824  *
825  */
826 typedef struct PACKED tdmr_info_entry_s
827 {
828     uint64_t tdmr_base;    /**< Base address of the TDMR (HKID bits must be 0). 1GB aligned. */
829     uint64_t tdmr_size;    /**< Size of the CMR, in bytes. 1GB aligned. */
830     uint64_t pamt_1g_base; /**< Base address of the PAMT_1G range associated with the above TDMR (HKID bits must be 0). 4K aligned. */
831     uint64_t pamt_1g_size; /**< Size of the PAMT_1G range associated with the above TDMR. 4K aligned. */
832     uint64_t pamt_2m_base; /**< Base address of the PAMT_2M range associated with the above TDMR (HKID bits must be 0). 4K aligned. */
833     uint64_t pamt_2m_size; /**< Size of the PAMT_2M range associated with the above TDMR. 4K aligned. */
834     uint64_t pamt_4k_base; /**< Base address of the PAMT_4K range associated with the above TDMR (HKID bits must be 0). 4K aligned. */
835     uint64_t pamt_4k_size; /**< Size of the PAMT_4K range associated with the above TDMR. 4K aligned. */
836 
837     struct
838     {
839         uint64_t offset; /**< Offset of reserved range 0 within the TDMR. 4K aligned. */
840         uint64_t size;   /**< Size of reserved range 0 within the TDMR. A size of 0 indicates a null entry. 4K aligned. */
841     } rsvd_areas[MAX_RESERVED_AREAS];
842 
843 } tdmr_info_entry_t;
```

### Validating tdmr_info passed from kernel and copy information

Because the tdmr_info is generated by the kernel side, TDX should verifies whether the information 
stored in the tdmr_info is benign and true. For that purpose below function is invoked. 

```cpp
656 static api_error_type check_and_set_tdmrs(tdmr_info_entry_t tdmr_info_copy[MAX_TDMRS],
657         uint64_t i, pamt_data_t pamt_data_array[])
```

After the validation, it stores the tdmr_info to the tdmr_table member field of tdx global_data structure.

```cpp
set_tdmr_info_in_global_data(tdmr_info_copy, (uint32_t)i);
```

## Key configuration for TDX module on entire packages (kernel side -> TDX SEAMCALL)
Let's go back to the kernel side initialization function **__tdx_init_module** function. After setting
up the TDMR information in the TDX module, kernel side invokes TDH_SYS_KEY_CONFIG seamcall to configure
key spaces used for encryption in MKTME. 

```cpp
1234         tdx_seam_keyid = tdx_keyids_start;
1235 
1236         /*
1237          * Cache Flush is required as
1238          * TDX module spec: Chapter 12 Intel TDX Module Lifecycle Table 12.1
1239          */
1240         wbinvd_on_all_cpus();
1241 
1242         /* Cpuslock is already held by the caller. */
1243         ret = tdx_seamcall_on_each_pkg_cpuslocked(do_tdh_sys_key_config, NULL);
1244         if (ret)
1245                 goto out;
```

Note that **tdx_seamcall_on_each_pkg_cpuslocked** invokes do_tdh_sys_key_config function per package,
which invokes the seamcall to TDX module.

```cpp
1180 static int do_tdh_sys_key_config(void *param)
1181 {
1182         u64 err;
1183 
1184         do {
1185                 err = tdh_sys_key_config();
1186         } while (err == TDX_KEY_GENERATION_FAILED);
1187         if (WARN_ON_ONCE(err)) {
1188                 pr_seamcall_error(SEAMCALL_TDH_SYS_KEY_CONFIG,
1189                                   "TDH_SYS_KEY_CONFIG", err, NULL);
1190                 return -EIO;
1191         }
1192 
1193         return 0;
1194 }
```

tdh_sys_key_config function invokes SEAMCALL, and processor jumps to the TDX dispatcher to handle
the TDH_SYS_KEY_CONFIG seamcall (by tdh_sys_key_config in TDX module side). Note that the above
tdh_sys_key_config is located in the kernel side and the other tdh_sys_key_config presented in the 
below code is located in the TDX module. 

```cpp
 23 api_error_type tdh_sys_key_config(void)    
 24 {                                          
 ......
 57     // Execute PCONFIG to configure the TDX-SEAM global private HKID on the package, with a CPU-generated random key.
 58     // PCONFIG may fail due to and entropy error or a device busy error.
 59     // In this case, the VMM should retry TDHSYSKEYCONFIG.
 60     retval = program_mktme_keys(tdx_global_data_ptr->hkid);
 61     if (retval != TDX_SUCCESS)
 62     {
 63         TDX_ERROR("Failed to program MKTME keys for this package\n");
 64         // Clear the package configured bit
 65         _lock_btr_32b(&tdx_global_data_ptr->pkg_config_bitmap, tdx_local_data_ptr->lp_info.pkg);
 66         goto EXIT;
 67     }
 68 
 69     // Update the number of initialized packages. If this is the last one, update the system state.
 70     tdx_global_data_ptr->num_of_init_pkgs++;
 71     if (tdx_global_data_ptr->num_of_init_pkgs == tdx_global_data_ptr->num_of_pkgs)
 72     {
 73         tdx_global_data_ptr->global_state.sys_state = SYS_READY;
 74     }
 75 
 76     retval = TDX_SUCCESS;
```

It sets the MKTME key for TDX module for current package. All information required to set 
mktme key is stored in the tdx_global_data_ptr including whether it provides the integrity,
how to generate the key, the algorithm for encryption &c. 


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

After setting all information, PCONFIG instruction is executed to set the key 
(refer to ia32_mktme_key_program function).

## TDMR initialization by the TDX module (TDH_SYS_TDMR_INIT)
```cpp
1264         ret = tdx_init_tdmrs();
1265 out:
1266         kfree(tdmr_addrs);
1267         return ret;
1268 }
```


```cpp
1140 static int tdx_init_tdmrs(void)
1141 {
1142         /*
1143          * One TDMR can be initialized only by one thread.  No point to have
1144          * threads more than the number of TDMRs.
1145          */
1146         int nr_works = min_t(int, num_online_cpus(), tdx_nr_tdmrs);
1147         struct tdx_tdmr_init_data data = {
1148                 .next_tdmr_index = 0,
1149                 .nr_initialized_tdmrs = 0,
1150                 .failed = 0,
1151                 .nr_completed = 0,
1152                 .nr_works = nr_works,
1153                 .completion = COMPLETION_INITIALIZER_ONSTACK(data.completion),
1154         };
1155         int i;
1156 
1157         struct tdx_tdmr_init_request *reqs = kcalloc(nr_works, sizeof(*reqs),
1158                                                      GFP_KERNEL);
1159         if (!reqs)
1160                 return -ENOMEM;
1161 
1162         mutex_init(&data.lock);
1163         for (i = 0; i < nr_works; i++) {
1164                 reqs[i].data = &data;
1165                 INIT_WORK(&reqs[i].work, __tdx_init_tdmrs);
1166                 queue_work(system_unbound_wq, &reqs[i].work);
1167         }
1168         wait_for_completion(&data.completion);
......
1178 }
```


```cpp
1075 static void __tdx_init_tdmrs(struct work_struct *work)
1076 {
1077         struct tdx_tdmr_init_request *req = container_of(
1078                 work, struct tdx_tdmr_init_request, work);
1079         struct tdx_tdmr_init_data *data = req->data;
......
1086         mutex_lock(&data->lock);
1087         while (data->next_tdmr_index < tdx_nr_tdmrs) {
1088                 i = data->next_tdmr_index++;
1089                 base = tdmr_info[i].base;
1090                 size = tdmr_info[i].size;
1091 
1092                 while (true) {
1093                         /* Abort if a different CPU failed. */
1094                         if (data->failed)
1095                                 goto out;
1096 
1097                         mutex_unlock(&data->lock);
1098                         err = tdh_sys_tdmr_init(base, &ex_ret);
1099                         if (WARN_ON_ONCE(err)) {
1100                                 pr_seamcall_error(SEAMCALL_TDH_SYS_TDMR_INIT,
1101                                                   "TDH_SYS_TDMR_INIT", err,
1102                                                   &ex_ret);
1103                                 err = -EIO;
1104                                 mutex_lock(&data->lock);
1105                                 goto out;
1106                         }
1107                         cond_resched();
1108                         mutex_lock(&data->lock);
1109 
1110                         /*
1111                          * Note, "next" is simply an indicator, base is passed
1112                          * to TDH.SYS.TDMR.INIT on every iteration.
1113                          */
1114                         if (!(ex_ret.sys_tdmr_init.next < (base + size)))
1115                                 break;
1116                 }
1117 
1118                 data->nr_initialized_tdmrs++;
1119         }
1120 
1121 out:
1122         if (err)
1123                 data->failed++;
1124         data->nr_completed++;
1125         completed = (data->nr_completed == data->nr_works);
1126         mutex_unlock(&data->lock);
1127 
1128         if (completed)
1129                 complete(&data->completion);
1130 }
```


### TDX module side TDMR init
```cpp
 32 api_error_type tdh_sys_tdmr_init(uint64_t tdmr_pa)
 33 {
 34 
 35     tdx_module_global_t* tdx_global_data_ptr;
 36     tdx_module_local_t* tdx_local_data = get_local_data();
 37     api_error_type retval;
 38     bool_t lock_acquired = false;
 39 
 40     tdx_local_data->vmm_regs.rdx = 0ULL;
 41 
 42     // For each TDMR, the VMM executes a loop of SEAMCALL(TDHSYSINITTDMR),
 43     // providing the TDMR start address (at 1GB granularity) as an input
 44     if (!is_addr_aligned_pwr_of_2(tdmr_pa, _1GB) ||
 45         !is_pa_smaller_than_max_pa(tdmr_pa) ||
 46         (get_hkid_from_pa((pa_t)tdmr_pa) != 0))
 47     {
 48         retval = api_error_with_operand_id(TDX_OPERAND_INVALID, OPERAND_ID_RCX);
 49         goto EXIT;
 50 
 51     }
 52 
 53     tdx_global_data_ptr = get_global_data();
 54 
 55     //   2.  Verify that the provided TDMR start address belongs to one of the TDMRs set during TDHSYSINIT
 56     uint32_t tdmr_index;
 57     for (tdmr_index = 0; tdmr_index < tdx_global_data_ptr->num_of_tdmr_entries; tdmr_index++)
 58     {
 59         if (tdmr_pa == tdx_global_data_ptr->tdmr_table[tdmr_index].base)
 60         {
 61             break;
 62         }
 63     }
 64     if (tdmr_index >= tdx_global_data_ptr->num_of_tdmr_entries)
 65     {
 66         retval = api_error_with_operand_id(TDX_OPERAND_INVALID, OPERAND_ID_RCX);
 67         goto EXIT;
 68     }
 69 
 70     tdmr_entry_t *tdmr_entry = &tdx_global_data_ptr->tdmr_table[tdmr_index];
 71 
 72     if (acquire_mutex_lock(&tdmr_entry->lock) != LOCK_RET_SUCCESS)
 73     {
 74         retval = api_error_with_operand_id(TDX_OPERAND_BUSY, OPERAND_ID_RCX);
 75         goto EXIT;
 76     }
 77 
 78     lock_acquired = true;
```



```cpp
 79 
 80     //   3.  Retrieves the TDMR’s next-to-initialize address from the internal TDMR data structure.
 81     //       If the next-to-initialize address is higher than the address to the last byte of the TDMR, there’s nothing to do.
 82     //       If successful, the function does the following:
 83     if (tdmr_entry->last_initialized >= (tdmr_entry->base + tdmr_entry->size))
 84     {
 85         retval = TDX_TDMR_ALREADY_INITIALIZED;
 86         goto EXIT;
 87     }
 88 
 89     //   4.  Initialize an (implementation defined) number of PAMT entries.
 90     //        The maximum number of PAMT entries to be initialized is set to avoid latency issues.
 91     //   5.  If the PAMT for a 1GB block of TDMR has been fully initialized, mark that 1GB block as ready for use.
 92     //        This means that 4KB pages in this 1GB block may be converted to private pages, e.g., by TDCALL(TDHMEMPAGEADD).
 93     //        This can be done concurrently with initializing other TDMRs.
 94 
 95     pamt_block_t pamt_block;
 96     pamt_block.pamt_1gb_p = (pamt_entry_t*) (tdmr_entry->pamt_1g_base
 97             + ((tdmr_entry->last_initialized - tdmr_entry->base) / _1GB * sizeof(pamt_entry_t)));
 98     pamt_block.pamt_2mb_p = (pamt_entry_t*) (tdmr_entry->pamt_2m_base
 99             + ((tdmr_entry->last_initialized - tdmr_entry->base) / _2MB * sizeof(pamt_entry_t)));
100     pamt_block.pamt_4kb_p = (pamt_entry_t*) (tdmr_entry->pamt_4k_base
101             + ((tdmr_entry->last_initialized - tdmr_entry->base) / _4KB * sizeof(pamt_entry_t)));
102 
103     pamt_init(&pamt_block, TDMR_4K_PAMT_INIT_COUNT, tdmr_entry);
```

It might not initialize entire PAMT associated with one TDMR at once because of latency issues. 
Therefore, the base addresses of PAMT should be calculated based on base addresses and last 
initialized addresses. Also maximum number of entries of PAMT that can be initialized at once 
is fixed. 

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

Because there are three different PAMT for specific TDMR range, it should initialize all three 
PAMTs covering that range. 



### PAMT node allocation for 1st and 2nd level (1GB, 2MB)

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

It doesn't register its virtual mappings to the PAMT phytsical enties, it makes temporal mapping to the PAMT entries
and clear its content and set page properties. Also, it initialize the MKTME settings for the PAMT addresses, which is
setting the upper physical bits of the PAMT physical addresses to make the addresses to be encrypted with MKTME. 


```cpp
_STATIC_INLINE_ void* map_pa_with_hkid(void* pa, uint16_t hkid, mapping_type_t mapping_type)
{
    pa_t temp_pa = {.raw_void = pa};
    pa_t pa_with_hkid = set_hkid_to_pa(temp_pa, hkid);
    return map_pa((void*) pa_with_hkid.raw, mapping_type);
}

_STATIC_INLINE_ void* map_pa_with_global_hkid(void* pa, mapping_type_t mapping_type)
{
    uint16_t tdx_global_hkid = get_global_data()->hkid;
    return map_pa_with_hkid(pa, tdx_global_hkid, mapping_type);
}
```

### PAMT allocation for 4kb entries
```cpp
 97 _STATIC_INLINE_ void pamt_4kb_init(pamt_block_t* pamt_block, uint64_t num_4k_entries, tdmr_entry_t *tdmr_entry)
 98 {
 99     pamt_entry_t* pamt_entry = NULL;
100     uint64_t current_4k_page_idx = ((uint64_t)pamt_block->pamt_4kb_p - tdmr_entry->pamt_4k_base)
101                                     / sizeof(pamt_entry_t);
102     uint64_t page_offset;
103     uint32_t last_rsdv_idx = 0;
104 
105     // PAMT_CHILD_ENTRIES pamt entries take more than 1 page size, this is why
106     // we need to do a new map each time we reach new page in the entries array
107     // Since we work with chunks of PAMT_CHILD_ENTRIES entries it time,
108     // the start address is always aligned on 4K page
109     uint32_t pamt_entries_in_page = TDX_PAGE_SIZE_IN_BYTES / sizeof(pamt_entry_t);
110     uint32_t pamt_pages = (uint32_t)(num_4k_entries / pamt_entries_in_page);
111         
112     pamt_entry_t* pamt_entry_start = pamt_block->pamt_4kb_p;
113     tdx_sanity_check(((uint64_t)pamt_entry_start % TDX_PAGE_SIZE_IN_BYTES) == 0,
114             SCEC_PAMT_MANAGER_SOURCE, 11);
115     for (uint32_t i = 0; i < pamt_pages; i++)
116     {
117         pamt_entry = map_pa_with_global_hkid(
118                 &pamt_entry_start[pamt_entries_in_page * i], TDX_RANGE_RW);
119         // create a cache aligned, cache sized chunk and fill it with 'val'
120         ALIGN(MOVDIR64_CHUNK_SIZE) pamt_entry_t chunk[PAMT_4K_ENTRIES_IN_CACHE];
121         basic_memset((uint64_t)chunk, PAMT_4K_ENTRIES_IN_CACHE*sizeof(pamt_entry_t), 0 , PAMT_4K_ENTRIES_IN_CACHE*sizeof(pamt_entry_t));
122         for (uint32_t j = 0; j < pamt_entries_in_page; j++, current_4k_page_idx++)
123         {
124             page_offset = current_4k_page_idx * TDX_PAGE_SIZE_IN_BYTES;
125             if (is_page_reserved(page_offset, tdmr_entry, &last_rsdv_idx))
126             {
127                 chunk[j%PAMT_4K_ENTRIES_IN_CACHE].pt = PT_RSVD;
128             }
129             else
130             {
131                 chunk[j%PAMT_4K_ENTRIES_IN_CACHE].pt = PT_NDA;
132                 last_rsdv_idx = 0;
133             }
134             if ((j+1)%PAMT_4K_ENTRIES_IN_CACHE == 0)
135             {
136                 fill_cachelines_no_sfence((void*)&(pamt_entry[j-3]), (uint8_t*)chunk, 1);
137             }
138         }
139         mfence();
140         free_la(pamt_entry);
141     }
142 }
```

First it calculates how many PAMT pages for 4k PAMT entries can be initialized (pamt_pages). 
And then iterates non-initialized pamt_entry and decide whether which page is reserved (PT_RSVD)
or normal TDX page (PT_NDA) that can be assigned to TD VM later. 




### Rest of the PAMT initialization

```cpp
104 
105     //   6.  Store the updated next-to-initialize address in the internal TDMR data structure.
106     tdmr_entry->last_initialized += (TDMR_4K_PAMT_INIT_COUNT * _4KB);
107 
108     //   7.  The returned next-to-initialize address is always rounded down to 1GB, so VMM won’t attempt to use a 1GB block that is not fully initialized.
109     tdx_local_data->vmm_regs.rdx = tdmr_entry->last_initialized & ~(_1GB - 1);
110 
111     retval = TDX_SUCCESS;
112 
113     EXIT:
114 
115     if (lock_acquired)
116     {
117         release_mutex_lock(&tdx_global_data_ptr->tdmr_table[tdmr_index].lock);
118     }
119 
120     return retval;
121 }
```





