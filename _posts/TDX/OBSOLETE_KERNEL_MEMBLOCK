## Memblock

Early system initialization cannot use “normal” memory management simply because it is not set up yet. But there is still need to allocate memory for various data structures, for instance for the physical page allocator

A specialized allocator called memblock performs the boot time memory management. 
The architecture specific initialization must set it up in setup_arch() and tear it down in mem_init() functions.

```cpp
+---------------------------+   +---------------------------+
|         memblock          |   |                           |
|  _______________________  |   |                           |
| |        memory         | |   |       Array of the        |
| |      memblock_type    |-|-->|      memblock_region      |
| |_______________________| |   |                           |
|                           |   +---------------------------+
|  _______________________  |   +---------------------------+
| |       reserved        | |   |                           |
| |      memblock_type    |-|-->|       Array of the        |
| |_______________________| |   |      memblock_region      |
|                           |   |                           |
+---------------------------+   +---------------------------+
```
[[https://0xax.gitbooks.io/linux-insides/content/MM/linux-mm-1.html]]


```cpp
struct memblock {
    bool bottom_up;
    phys_addr_t current_limit;
    struct memblock_type memory;
    struct memblock_type reserved;
};
```
### Memblock Overview
Memblock is a method of managing memory regions during the early boot period when the usual kernel memory allocators are not up and running.


Memblock views the system memory as collections of contiguous regions. There are several types of these collections:

memory - describes the physical memory available to the kernel; this may differ from the actual physical memory installed in the system, for instance when the memory is restricted with mem= command line parameter

reserved - describes the regions that were allocated

physmem - describes the actual physical memory available during boot regardless of the possible restrictions and memory hot(un)plug; the physmem type is only available on some architectures.


Each region is represented by struct memblock_region that defines the region extents, its attributes and NUMA node id on NUMA systems. Every memory type is described by the struct memblock_type which contains an array of memory regions along with the allocator metadata. The “memory” and “reserved” types are nicely wrapped with struct memblock. This structure is statically initialized at build time



### Utilizing initialized memblocks
Once memblock is setup the memory can be allocated using one of the API variants:

memblock_phys_alloc*() - these functions return the physical address of the allocated memory

memblock_alloc*() - these functions return the virtual address of the allocated memory.


Consult the documentation of memblock_alloc_internal() and memblock_alloc_range_nid() .


### Freeing memblock
As the system boot progresses, the architecture specific mem_init() function frees 
all the memory to the buddy page allocator.
Unless an architecture enables CONFIG_ARCH_KEEP_MEMBLOCK, the memblock data structures (except “physmem”) will be discarded after the system initialization completes.


```cpp
static void __init mm_init(void)
{       
        /*
         * page_ext requires contiguous pages,
         * bigger than MAX_ORDER unless SPARSEMEM.
         */
        page_ext_init_flatmem();
        init_mem_debugging_and_hardening();
        kfence_alloc_pool();
        report_meminit();
        stack_depot_early_init();
        mem_init();
        mem_init_print_info();
        kmem_cache_init();
        /* 
         * page_owner must be initialized after buddy is ready, and also after
         * slab is ready so that stack_depot_init() works properly
         */
        page_ext_init_flatmem_late();
        kmemleak_init();
        pgtable_init();
        debug_objects_mem_init();
        vmalloc_init();
        /* Should be run before the first non-init thread is created */
        init_espfix_bsp();
        /* Should be run after espfix64 is set up. */
        pti_init();
}

```
```cpp
void __init mem_init(void)
{
        pci_iommu_alloc();

        /* clear_bss() already clear the empty_zero_page */

        /* this will put all memory onto the freelists */
        memblock_free_all();
        after_bootmem = 1;
        x86_init.hyper.init_after_bootmem();
        
        /*
         * Must be done after boot memory is put on freelist, because here we
         * might set fields in deferred struct pages that have not yet been
         * initialized, and memblock_free_all() initializes all the reserved
         * deferred pages for us.
         */
        register_page_bootmem_info();

        /* Register memory areas for /proc/kcore */
        if (get_gate_vma(&init_mm))
                kclist_add(&kcore_vsyscall, (void *)VSYSCALL_ADDR, PAGE_SIZE, KCORE_USER);

        preallocate_vmalloc_pages();
}

```

https://docs.kernel.org/core-api/boot-time-mm.html





