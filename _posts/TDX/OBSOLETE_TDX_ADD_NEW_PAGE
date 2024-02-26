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
