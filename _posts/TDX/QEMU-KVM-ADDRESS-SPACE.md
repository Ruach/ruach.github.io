## QEMU side memory management 
>**The MemoryRegion is the link between guest physical address space and the 
>RAMBlocks containing the memory**. Each MemoryRegion has the ram_addr_t offset 
>of the RAMBlock and each RAMBlock has a MemoryRegion pointer.
>Note that MemoryRegion is more general than just RAM. It can also represent I/O
>memory where read/write callback functions are invoked on access. This is how 
>hardware register accesses from a guest CPU are dispatched to emulated devices.
>The address_space_rw() function dispatches load/store accesses to the 
>appropriate MemoryRegions. If a MemoryRegion is a RAM region then the data will
>be accessed from the RAMBlock's mmapped guest RAM. The **address_space_memory** 
>global variable is the guest physical memory space.

http://blog.vmsplice.net/2016/01/qemu-internals-how-guest-physical-ram.html


>A region is created by one of the memory_region_init*() functions and attached
>to an object, which acts as its owner or parent. QEMU ensures that the owner 
>object remains alive as long as the region is visible to the guest, or as long
>as the region is in use by a virtual CPU or another device. After creation, a 
>**region can be added to an address space or a container** with 
>memory_region_add_subregion(), and removed using memory_region_del_subregion().

https://qemu.weilnetz.de/doc/devel/memory.html


### Important data structures managing VMs on QEMU side 
```cpp
struct KVMState
{
    AccelState parent_obj;

    int nr_slots;
    int fd;
    int vmfd;
    int coalesced_mmio;
    int coalesced_pio;
    struct kvm_coalesced_mmio_ring *coalesced_mmio_ring;
    bool coalesced_flush_in_progress;
    int vcpu_events;
    int robust_singlestep;
    int debugregs;
    ......
    KVMMemoryListener memory_listener;
    QLIST_HEAD(, KVMParkedVcpu) kvm_parked_vcpus;

    /* For "info mtree -f" to tell if an MR is registered in KVM */
    int nr_as;
    struct KVMAs {
        KVMMemoryListener *ml;
        AddressSpace *as;
    } *as;
```
In QEMU, KVMState is a data structure that represents the state of a virtual 
machine managed by the Kernel-based Virtual Machine (KVM) hypervisor. The 
KVMState structure contains various fields that represent the virtual machine's 
CPU state, memory state, device state, and other properties.

The KVMState structure is used extensively throughout QEMU to manage the state 
of virtual machines running under the KVM hypervisor. QEMU uses the KVMState 
structure to initialize and configure the virtual machine, handle interrupts and
other events, and manage interactions between the virtual machine and the host. 

```cpp
struct MemoryRegion {
    Object parent_obj;

    /* private: */         
                           
    /* The following fields should fit in a cache line */
    bool romd_mode;        
    bool ram;              
    bool subpage;
    bool readonly; /* For RAM regions */
    bool nonvolatile;
    bool rom_device;
    bool flush_coalesced_mmio;
    uint8_t dirty_log_mask;
    bool is_iommu;
    RAMBlock *ram_block;
    Object *owner;                    
                                      
    const MemoryRegionOps *ops;       
    ......
```

```cpp
/**
 * struct AddressSpace: describes a mapping of addresses to #MemoryRegion objects
 */
struct AddressSpace {
    /* private: */
    struct rcu_head rcu;
    char *name;
    MemoryRegion *root;

    /* Accessed via RCU.  */
    struct FlatView *current_map;

    int ioeventfd_nb;
    struct MemoryRegionIoeventfd *ioeventfds;
    QTAILQ_HEAD(, MemoryListener) listeners;
    QTAILQ_ENTRY(AddressSpace) address_spaces_link;
};
```


```cpp
struct RAMBlock {
    struct rcu_head rcu;
    struct MemoryRegion *mr;
    uint8_t *host;
    uint8_t *colo_cache; /* For colo, VM's ram cache */
    ram_addr_t offset;
    ram_addr_t used_length;
    ram_addr_t max_length;
    void (*resized)(const char*, uint64_t length, void *host);
    uint32_t flags;
    /* Protected by iothread lock.  */
    char idstr[256];
    /* RCU-enabled, writes protected by the ramlist lock */
    QLIST_ENTRY(RAMBlock) next;
    QLIST_HEAD(, RAMBlockNotifier) ramblock_notifiers;
    int fd;
    int private_fd;
    size_t page_size;
    /* dirty bitmap used during migration */
    unsigned long *bmap;
    /* bitmap of already received pages in postcopy */
    unsigned long *receivedmap;
```

### For TDX
Because RAMBlock is a basic unit to manage the memories for the VM instances,
it extends the RAMBlock to support private memory and shared memory in one 
RAMBlock. Note that it has two member fields (fd and private_fd) for shared and
private address space, respectively. 

## Memory region & address space initialization
### Global structures for memory and IO for VMs 
```cpp
static MemoryRegion *system_memory;
static MemoryRegion *system_io;

AddressSpace address_space_io;
AddressSpace address_space_memory;
```
Globally, regardless of the architecture, MemoryRegion and AddressSpace for 
system memory and IO are required to provide memory and IO for the VMs. 

### Initialize address space 
```cpp
static void qemu_create_machine(QDict *qdict)
{
    MachineClass *machine_class = select_machine(qdict, &error_fatal);
    object_set_machine_compat_props(machine_class->compat_props);

    set_memory_options(machine_class);

    current_machine = MACHINE(object_new_with_class(OBJECT_CLASS(machine_class)));
    object_property_add_child(object_get_root(), "machine",
                              OBJECT(current_machine));
    object_property_add_child(container_get(OBJECT(current_machine),
                                            "/unattached"),
                              "sysbus", OBJECT(sysbus_get_default()));

    if (machine_class->minimum_page_bits) {
        if (!set_preferred_target_page_bits(machine_class->minimum_page_bits)) {
            /* This would be a board error: specifying a minimum smaller than
             * a target's compile-time fixed setting.
             */
            g_assert_not_reached();
        }
    }

    cpu_exec_init_all();
......
}
```

```cpp
void cpu_exec_init_all(void)
{                                           
    qemu_mutex_init(&ram_list.mutex);
    finalize_target_page_bits();
    io_mem_init();
    memory_map_init();
    qemu_mutex_init(&map_client_list_lock);
}   
```

```cpp
static void memory_map_init(void)
{
    system_memory = g_malloc(sizeof(*system_memory));

    memory_region_init(system_memory, NULL, "system", UINT64_MAX);
    address_space_init(&address_space_memory, system_memory, "memory");

    system_io = g_malloc(sizeof(*system_io));
    memory_region_init_io(system_io, NULL, &unassigned_io_ops, NULL, "io",
                          65536);
    address_space_init(&address_space_io, system_io, "I/O");
}
```

This is where the system_memory and system_io memory region is allocated and 
initialized. memory_region_init function initialize some member fields such as 
name and size. The initialized **memory region is registered as the root memory 
region of corresponding address spaces by the address_space_init function.** 

```cpp
void address_space_init(AddressSpace *as, MemoryRegion *root, const char *name)
{   
    memory_region_ref(root);
    as->root = root;
    as->current_map = NULL;
    as->ioeventfd_nb = 0; 
    as->ioeventfds = NULL;
    QTAILQ_INIT(&as->listeners);
    QTAILQ_INSERT_TAIL(&address_spaces, as, address_spaces_link);
    as->name = g_strdup(name ? name : "anonymous");
    address_space_update_topology(as);
    address_space_update_ioeventfdy(as);
}       
```
Now the system_memory and system_io are registered as the root memory regions of
the address_space_memory and address_space_io, respectively. However, note that 
it just established links between the memory region and the address space, and 
there is no actual memory registered for those two address spaces. 


## Real memory allocation through RAMBlock
```cpp
/* PC hardware initialisation */
static void pc_init1(MachineState *machine,
                     const char *host_type, const char *pci_type)
{
    PCMachineState *pcms = PC_MACHINE(machine);
    PCMachineClass *pcmc = PC_MACHINE_GET_CLASS(pcms);
    X86MachineState *x86ms = X86_MACHINE(machine);
    MemoryRegion *system_memory = get_system_memory();
    MemoryRegion *system_io = get_system_io();
......
    if (pcmc->pci_enabled) {
        pci_memory = g_new(MemoryRegion, 1);
        memory_region_init(pci_memory, NULL, "pci", UINT64_MAX);
        rom_memory = pci_memory;
    } else {
......
    /* allocate ram and load rom/bios */
    if (!xen_enabled()) {
        pc_memory_init(pcms, system_memory,
                       rom_memory, &ram_memory);
    } else {

```

```cpp
void pc_memory_init(PCMachineState *pcms,
                    MemoryRegion *system_memory,
                    MemoryRegion *rom_memory,
                    MemoryRegion **ram_memory)
{
    int linux_boot, i;
    MemoryRegion *option_rom_mr;
    MemoryRegion *ram_below_4g, *ram_above_4g;
......
    *ram_memory = machine->ram;
    ram_below_4g = g_malloc(sizeof(*ram_below_4g));
    memory_region_init_alias(ram_below_4g, NULL, "ram-below-4g", machine->ram,
                             0, x86ms->below_4g_mem_size);
    memory_region_add_subregion(system_memory, 0, ram_below_4g);
    e820_add_entry(0, x86ms->below_4g_mem_size, E820_RAM);
    if (x86ms->above_4g_mem_size > 0) {
        ram_above_4g = g_malloc(sizeof(*ram_above_4g));
        memory_region_init_alias(ram_above_4g, NULL, "ram-above-4g",
                                 machine->ram,
                                 x86ms->below_4g_mem_size,
                                 x86ms->above_4g_mem_size);
        memory_region_add_subregion(system_memory, 0x100000000ULL,
                                    ram_above_4g);
        e820_add_entry(0x100000000ULL, x86ms->above_4g_mem_size, E820_RAM);
    }

```

### Register new memory region as a subregion
memory_region_add_subregion function registers the newly generated memory region 
to the existing memory region as a sub-region. The param mr is the existing 
memory region, and the subregion is the newly generated memory region that will
be registered to the mr. The offset is the GPA of the new memory region. 

```cpp
void memory_region_add_subregion(MemoryRegion *mr,
                                 hwaddr offset,
                                 MemoryRegion *subregion)
{
    subregion->priority = 0;
    memory_region_add_subregion_common(mr, offset, subregion);
}
```

```cpp
static void memory_region_add_subregion_common(MemoryRegion *mr,
                                               hwaddr offset,
                                               MemoryRegion *subregion)
{
    MemoryRegion *alias;

    assert(!subregion->container);
    subregion->container = mr;
    for (alias = subregion->alias; alias; alias = alias->alias) {
        alias->mapped_via_alias++;
    }
    subregion->addr = offset;
    memory_region_update_container_subregions(subregion);
}
```

```cpp
static void memory_region_update_container_subregions(MemoryRegion *subregion)
{
    MemoryRegion *mr = subregion->container;
    MemoryRegion *other;

    memory_region_transaction_begin();

    memory_region_ref(subregion);
    QTAILQ_FOREACH(other, &mr->subregions, subregions_link) {
        if (subregion->priority >= other->priority) {
            QTAILQ_INSERT_BEFORE(other, subregion, subregions_link);
            goto done;
        }
    }
    QTAILQ_INSERT_TAIL(&mr->subregions, subregion, subregions_link);
done:
    memory_region_update_pending |= mr->enabled && subregion->enabled;
    memory_region_transaction_commit();
}
```
Because the sub-regions of one memory region are maintained by the subregions 
member field of the root MemoryRegion, the newly generated sub-region should
also be registered in that list. Now the sub-region is successfully registered
in the subregions list of the root MemoryRegion. However, note that this link
was established on QEMU side, which further requires KVM side memory management. 
Remember that the subregions are maintained as a tree form and should be
translated into the **flatview** to be processed by the KVM side easily. Refer
to [[]] about flatview. 

## Notify new memory region to KVM side
```cpp
static void kvm_region_add(MemoryListener *listener,
                           MemoryRegionSection *section)
{
    KVMMemoryListener *kml = container_of(listener, KVMMemoryListener, listener);

    memory_region_ref(section->mr);
    kvm_set_phys_mem(kml, section, true);
}
```
kvm_region_add function is registered as the region_add hook function of the 
KVMMemoryListener. Therefore, it will be invoked whenever XXX (Not sure when
it is actually invoked..)

```cpp
static void kvm_set_phys_mem(KVMMemoryListener *kml,
                             MemoryRegionSection *section, bool add)
{
    KVMSlot *mem;
    int err;
    MemoryRegion *mr = section->mr;
    bool writeable = !mr->readonly && !mr->rom_device;
    hwaddr start_addr, size, slot_size, mr_offset;
    ram_addr_t ram_start_offset;
    void *ram;

    if (!memory_region_is_ram(mr)) {
        if (writeable || !kvm_readonly_mem_allowed) {
            return;
        } else if (!mr->romd_mode) {
            /* If the memory device is not in romd_mode, then we actually want
             * to remove the kvm memory slot so all accesses will trap. */
            add = false;
        }
    }

    size = kvm_align_section(section, &start_addr);
    if (!size) {
        return;
    }

    /* The offset of the kvmslot within the memory region */
    mr_offset = section->offset_within_region + start_addr -
        section->offset_within_address_space;

    /* use aligned delta to align the ram address and offset */
    ram = memory_region_get_ram_ptr(mr) + mr_offset;
    ram_start_offset = memory_region_get_ram_addr(mr) + mr_offset;

    kvm_slots_lock();

    if (!add) {
        do {
            slot_size = MIN(kvm_max_slot_size, size);
            mem = kvm_lookup_matching_slot(kml, start_addr, slot_size);
            if (!mem) {
                goto out;
            }
            if (mem->flags & KVM_MEM_LOG_DIRTY_PAGES) {
                /*
                 * NOTE: We should be aware of the fact that here we're only
                 * doing a best effort to sync dirty bits.  No matter whether
                 * we're using dirty log or dirty ring, we ignored two facts:
                 *
                 * (1) dirty bits can reside in hardware buffers (PML)
                 *
                 * (2) after we collected dirty bits here, pages can be dirtied
                 * again before we do the final KVM_SET_USER_MEMORY_REGION to
                 * remove the slot.
                 *
                 * Not easy.  Let's cross the fingers until it's fixed.
                 */
                if (kvm_state->kvm_dirty_ring_size) {
                    kvm_dirty_ring_reap_locked(kvm_state);
                } else {
                    kvm_slot_get_dirty_log(kvm_state, mem);
                }
                kvm_slot_sync_dirty_pages(mem);
            }

            /* unregister the slot */
            g_free(mem->dirty_bmap);
            mem->dirty_bmap = NULL;
            mem->memory_size = 0;
            mem->flags = 0;
            err = kvm_set_user_memory_region(kml, mem, false);
            if (err) {
                fprintf(stderr, "%s: error unregistering slot: %s\n",
                        __func__, strerror(-err));
                abort();
            }
            start_addr += slot_size;
            size -= slot_size;
        } while (size);
        goto out;
    }

    /* register the new slot */
    do {
        slot_size = MIN(kvm_max_slot_size, size);
        mem = kvm_alloc_slot(kml);
        mem->as_id = kml->as_id;
        mem->memory_size = slot_size;
        mem->start_addr = start_addr;
        mem->ram_start_offset = ram_start_offset;
        mem->ram = ram;
        mem->flags = kvm_mem_flags(mr);
        if (mem->flags & KVM_MEM_PRIVATE) {
            mem->fd = mr->ram_block->private_fd;
            mem->ofs = (uint8_t*)ram - mr->ram_block->host;
        } else {
            mem->fd = -1;
            mem->ofs = -1;
        }
        kvm_slot_init_dirty_bitmap(mem);
        err = kvm_set_user_memory_region(kml, mem, true);
        if (err) {
            fprintf(stderr, "%s: error registering slot: %s\n", __func__,
                    strerror(-err));
            abort();
        }
        start_addr += slot_size;
        ram_start_offset += slot_size;
        ram += slot_size;
        size -= slot_size;
    } while (size);

out:
    kvm_slots_unlock();
}
```

### Get KVMSlot for new memory
```cpp
typedef struct KVMSlot
{
    hwaddr start_addr;
    ram_addr_t memory_size;
    void *ram;
    int slot;
    int flags;
    int old_flags;
    /* Dirty bitmap cache for the slot */
    unsigned long *dirty_bmap;
    unsigned long dirty_bmap_size;
    /* Cache of the address space ID */
    int as_id;
    /* Cache of the offset in ram address space */
    ram_addr_t ram_start_offset;
    int fd;
    hwaddr ofs;
} KVMSlot;
```

```cpp
/* Called with KVMMemoryListener.slots_lock held */
static KVMSlot *kvm_alloc_slot(KVMMemoryListener *kml)
{
    KVMSlot *slot = kvm_get_free_slot(kml);

    if (slot) {
        return slot;
    }

    fprintf(stderr, "%s: no free slot available\n", __func__);
    abort();
}

```

```cpp
/* Called with KVMMemoryListener.slots_lock held */
static KVMSlot *kvm_get_free_slot(KVMMemoryListener *kml)
{
    KVMState *s = kvm_state;
    int i;

    for (i = 0; i < s->nr_slots; i++) {
        if (kml->slots[i].memory_size == 0) {
            return &kml->slots[i];
        }
    }

    return NULL;
}
```

### KVM_SET_USER_MEMORY_REGION ioctl to communicate with KVM
```cpp
static int kvm_set_user_memory_region(KVMMemoryListener *kml, KVMSlot *slot, bool new)
{
    KVMState *s = kvm_state;
    struct kvm_userspace_memory_region_ext mem;
    int ret;

    mem.region.slot = slot->slot | (kml->as_id << 16);
    mem.region.guest_phys_addr = slot->start_addr;
    mem.region.userspace_addr = (unsigned long)slot->ram;
    mem.region.flags = slot->flags;
    if (slot->flags & KVM_MEM_PRIVATE) {
        mem.private_fd = slot->fd;
        mem.private_offset = slot->ofs;
    } else {
        mem.private_fd = -1;
        mem.private_offset = -1;
    }
    if (kvm_tdx_enabled() && !(slot->flags & KVM_MEM_PRIVATE)) {
        warn_report("%s: Non-private memory backend is used for TDX"
                    " slot %d,"
                    " start_addr 0x%" PRIx64 ","
                    " ram 0x%" PRIx64 ","
                    " size 0x%" PRIx64 ","
                    " flags 0x%x",
                    __func__, mem.region.slot, slot->start_addr,
                    (uint64_t)slot->ram, slot->memory_size, slot->flags);
    }

    if (slot->memory_size && !new &&
        (slot->flags ^ slot->old_flags) & KVM_MEM_READONLY) {
        /* Set the slot size to 0 before setting the slot to the desired
         * value. This is needed based on KVM commit 75d61fbc. */
        mem.region.memory_size = 0;
        ret = kvm_vm_ioctl(s, KVM_SET_USER_MEMORY_REGION, &mem);
        if (ret < 0) {
            goto err;
        }
    }
    mem.region.memory_size = slot->memory_size;
    ret = kvm_vm_ioctl(s, KVM_SET_USER_MEMORY_REGION, &mem);
    slot->old_flags = mem.region.flags;
err:
    trace_kvm_set_user_memory(mem.region.slot, mem.region.flags,
                              mem.region.guest_phys_addr, mem.region.memory_size,
                              mem.region.userspace_addr, ret);
    if (ret < 0) {
        error_report("%s: KVM_SET_USER_MEMORY_REGION failed, slot=%d,"
                     " start=0x%" PRIx64 ", size=0x%" PRIx64 ","
                     " flags=0x%" PRIx32 ","
                     " private_fd=%" PRId32 ", private_offset=0x%" PRIx64 ": %s",
                     __func__, mem.region.slot, slot->start_addr,
                     (uint64_t)mem.region.memory_size, mem.region.flags,
                     mem.private_fd, (uint64_t)mem.private_offset,
                     strerror(errno));
    }
    return ret;
}
```

```cpp
/* for KVM_SET_USER_MEMORY_REGION */
struct kvm_userspace_memory_region {
        __u32 slot;
        __u32 flags;
        __u64 guest_phys_addr;
        __u64 memory_size; /* bytes */
        __u64 userspace_addr; /* start of the userspace allocated memory */
};
    
struct kvm_userspace_memory_region_ext {
        struct kvm_userspace_memory_region region;
        __u64 private_offset;
        __u32 private_fd;
        __u32 pad1;
        __u64 pad2[14];
};  
```

KVM_SET_USER_MEMORY_REGION ioctl allows kvm to initialize memory set by the 
QEMU. It also generates the kvm_userspace_memory_region_ext type parameter to 
let kvm understand which memory region should be created and assigned for the 
guest VM.





### Allocate and assign memory for new memory region
After the QEMU and KVM initialization for root memory regions of system memory 
and IO, another memory region might need to be generated and registered as a 
sub-region of the other region. For example guest VM requires virtual memory. 
QEMU reserves MemoryRegion called RAM region and makes them available to the 
guest VM as needed. 

The actual host memory region is represented as RAMBlock, and it is allocated 
by memory_region_init_ram function.

```cpp
void memory_region_init_ram(MemoryRegion *mr,
                            Object *owner,
                            const char *name,
                            uint64_t size,
                            Error **errp)
{       
    DeviceState *owner_dev;
    Error *err = NULL;
    
    memory_region_init_ram_nomigrate(mr, owner, name, size, &err);
    if (err) {
        error_propagate(errp, err);
        return;
    }       
    /* This will assert if owner is neither NULL nor a DeviceState.
     * We only want the owner here for the purposes of defining a
     * unique name for migration. TODO: Ideally we should implement
     * a naming scheme for Objects which are not DeviceStates, in
     * which case we can relax this restriction.
     */
    owner_dev = DEVICE(owner);
    vmstate_register_ram(mr, owner_dev);
    }
```

The MemoryRegion parameter is the newly allocated memory region that needs to be
initialized. Note that this function's main role is an allocating memory space 
for current memory region. The memory region is a meta-data presenting the 
actual memory. The actual memory space assigned for this memory region is 
presented by the RAMBlock type member field **ram_block**.

```cpp
void memory_region_init_ram_nomigrate(MemoryRegion *mr,
                                      Object *owner,
                                      const char *name,
                                      uint64_t size,
                                      Error **errp)
{
    memory_region_init_ram_flags_nomigrate(mr, owner, name, size, 0, errp);
}

void memory_region_init_ram_flags_nomigrate(MemoryRegion *mr,
                                            Object *owner,
                                            const char *name,
                                            uint64_t size,
                                            uint32_t ram_flags,
                                            Error **errp)
{
    Error *err = NULL;
    memory_region_init(mr, owner, name, size);
    mr->ram = true;
    mr->terminates = true;
    mr->destructor = memory_region_destructor_ram;
    mr->ram_block = qemu_ram_alloc(size, ram_flags, mr, &err);
    if (err) {
        mr->size = int128_zero();
        object_unparent(OBJECT(mr));
        error_propagate(errp, err);
    }
}
```

RAMBlock is allocated and assigned to the current memory region through the 
qemu_ram_alloc function. Note that the allocated memory is assigned to the 
ram_block member field of the current memory region. The memory is the part of 
the QEMU's address space which is a HVA in terms of virtualization. 



## Render flatview
To render the flatview, it is required to invoke flatviews_init, 
generate_memory_topology, and address_space_set_flatview. The flatviews_reset
function does invoke first two functions flatviews_init and 
generate_memory_topology. After the flatviews are reset, it invokes the last 
function, address_space_set_flatview, to update the QEMU and KVM data structures
corresponding to the new memory region addition. Recall that the last function 
further invokes address_space_update_topology_pass and region_add of the 
listener.

```cpp
void memory_region_transaction_commit(void)
{
    AddressSpace *as;

    assert(memory_region_transaction_depth);
    assert(qemu_mutex_iothread_locked());

    --memory_region_transaction_depth;
    if (!memory_region_transaction_depth) {
        if (memory_region_update_pending) {
            flatviews_reset();

            MEMORY_LISTENER_CALL_GLOBAL(begin, Forward);

            QTAILQ_FOREACH(as, &address_spaces, address_spaces_link) {
                address_space_set_flatview(as);
                address_space_update_ioeventfds(as);
            }
            memory_region_update_pending = false;
            ioeventfd_update_pending = false;
            MEMORY_LISTENER_CALL_GLOBAL(commit, Forward);
        } else if (ioeventfd_update_pending) {
            QTAILQ_FOREACH(as, &address_spaces, address_spaces_link) {
                address_space_update_ioeventfds(as);
            }
            ioeventfd_update_pending = false;
        }
   }
}
```

```cpp
static void flatviews_reset(void)
{
    AddressSpace *as;

    if (flat_views) {
        g_hash_table_unref(flat_views);
        flat_views = NULL;
    }
    flatviews_init();

    /* Render unique FVs */
    QTAILQ_FOREACH(as, &address_spaces, address_spaces_link) {
        MemoryRegion *physmr = memory_region_get_flatview_root(as->root);

        if (g_hash_table_lookup(flat_views, physmr)) {
            continue;
        }

        generate_memory_topology(physmr);
    }
}
```

Note that this function reset the flat_views and generate the memory topology 
for existing address space. Note that generate_memory_topology function is 
called, when the memory topology for address space doesn't exist. 



XXX{Move below to up}
Create a series of MemoryRegions, which respectively represent the RAM, ROM and
other areas in the Guest. The relationship between MemoryRegions is maintained 
through alias or subregions, thereby further refining the definition of the 
region AddressSpace represents the physical address space of the Guest. 


If the 
MemoryRegion in AddressSpace changes, the registered listener will be triggered,
expand the MemoryRegion tree to generate a one-dimensional FlatView, and compare
whether the FlatRange has changed. If it is, call the corresponding method to 
check the MemoryRegionSection, update the KVMSlot in QEMU, and fill in the 
kvm_userspace_memory_regionstructure at the same time, as ioctl()a parameter to
update the KVM in KVMkvm_memory_slot



[[]]
http://blog.vmsplice.net/2016/01/qemu-internals-how-guest-physical-ram.html




## Register KVM memory listener to AddressSpace
Adding actual memories to the address space is done through the registered 
listener. The registered KVM listener bridges the QEMU and KVM module so that 
its operation such as region_add and region_del talks to KVM module and register 
memory to the VMs managed by the QEMU. Note that KVM managed actual memories,
but the QEMU assigns the memory for the guest VM. When memory related events 
happen on the address space where the KVM listener is registered to, it delivers
the event to KVM module.


```cpp
static int kvm_init(MachineState *ms)
{
.....
    kvm_state = s;

    ret = kvm_arch_init(ms, s);
......
    kvm_memory_listener_register(s, &s->memory_listener,
                                 &address_space_memory, 0, "kvm-memory");
```

```cpp
typedef struct KVMMemoryListener {
    MemoryListener listener;
    KVMSlot *slots;
    int as_id;
} KVMMemoryListener;
```

Note that memory_listener is KVMMemoryListener type variable which is member 
field of KVMState. Also struct MemoryListener in KVMMemoryListener provides 
callbacks functions required for updates to the physical memory map.

```cpp
void kvm_memory_listener_register(KVMState *s, KVMMemoryListener *kml,
                                  AddressSpace *as, int as_id, const char *name)
{   
    int i;
    
    kml->slots = g_new0(KVMSlot, s->nr_slots);
    kml->as_id = as_id;

    for (i = 0; i < s->nr_slots; i++) {
        kml->slots[i].slot = i;
    }
    
    kml->listener.region_add = kvm_region_add;
    kml->listener.region_del = kvm_region_del;
    kml->listener.log_start = kvm_log_start;
    kml->listener.log_stop = kvm_log_stop; 
    kml->listener.priority = 10;  
    kml->listener.name = name;

    if (s->kvm_dirty_ring_size) {
        kml->listener.log_sync_global = kvm_log_sync_global;
    } else {
        kml->listener.log_sync = kvm_log_sync;
        kml->listener.log_clear = kvm_log_clear;
    }

    memory_listener_register(&kml->listener, as);

    for (i = 0; i < s->nr_as; ++i) {
        if (!s->as[i].as) {
            s->as[i].as = as;
            s->as[i].ml = kml;
            break;
        }
    }
}
```

kvm_memory_listener_register function allocates the callback functions needed 
for updates to physical memory map. Note that it assigns kvm_region_{add, del} 
functions as callbacks. 


```cpp
void memory_listener_register(MemoryListener *listener, AddressSpace *as)
{
    MemoryListener *other = NULL;
        
    /* Only one of them can be defined for a listener */
    assert(!(listener->log_sync && listener->log_sync_global));
            
    listener->address_space = as;
    if (QTAILQ_EMPTY(&memory_listeners)
        || listener->priority >= QTAILQ_LAST(&memory_listeners)->priority) {
        QTAILQ_INSERT_TAIL(&memory_listeners, listener, link);
    } else {
        QTAILQ_FOREACH(other, &memory_listeners, link) {
            if (listener->priority < other->priority) {
                break;
            } 
        }
        QTAILQ_INSERT_BEFORE(other, listener, link);
    }

    if (QTAILQ_EMPTY(&as->listeners)
        || listener->priority >= QTAILQ_LAST(&as->listeners)->priority) {
        QTAILQ_INSERT_TAIL(&as->listeners, listener, link_as);
    } else {
        QTAILQ_FOREACH(other, &as->listeners, link_as) {
            if (listener->priority < other->priority) {
                break;
            }
        }
        QTAILQ_INSERT_BEFORE(other, listener, link_as);
    }

    listener_add_address_space(listener, as);
}
```


```cpp
static void listener_add_address_space(MemoryListener *listener,
                                       AddressSpace *as)
{
    FlatView *view;
    FlatRange *fr;

    if (listener->begin) {
        listener->begin(listener);
    }
    if (global_dirty_tracking) {
        if (listener->log_global_start) {
            listener->log_global_start(listener);
        }
    }

    view = address_space_get_flatview(as);
    FOR_EACH_FLAT_RANGE(fr, view) {
        MemoryRegionSection section = section_from_flat_range(fr, view);

        if (listener->region_add) {
            listener->region_add(listener, &section);
        }
        if (fr->dirty_log_mask && listener->log_start) {
            listener->log_start(listener, &section, 0, fr->dirty_log_mask);
        }
    }
    if (listener->commit) {
        listener->commit(listener);
    }
    flatview_unref(view);
}
```

Recall that we were adding listener to the address_space_memory during the kvm 
initialization (kvm_init). Therefore, the address_space_memory is empty at this 
moment, and it will not invoke the region_add function of the listener. 





### FlatView as a medium between QEMU and KVM 
The domain of AddressSpace root and its subtree together constitute the physical
address space of the Guest, but these are defined on the QEMU side. When passing
in KVM for setting, the complex tree structure is not conducive to the kernel's
processing, so it needs to be converted into a "flat" address model, that is, a
data structure that starts from zero and only contains address information. This
is represented by FlatView in QEMU . Each AddressSpace has a corresponding 
FlatView pointer current_map, indicating its corresponding flat view.


```cpp
static void address_space_update_topology(AddressSpace *as)
{
    MemoryRegion *physmr = memory_region_get_flatview_root(as->root);

    flatviews_init();
    if (!g_hash_table_lookup(flat_views, physmr)) {
        generate_memory_topology(physmr);
    }
    address_space_set_flatview(as);
}
```

Recall that each AddressSpace has root memory region associated with it. For 
example, for address_space_memory has system_memory as its root memory region.

```cpp
static MemoryRegion *memory_region_get_flatview_root(MemoryRegion *mr)
{
    while (mr->enabled) {
        if (mr->alias) {
            if (!mr->alias_offset && int128_ge(mr->size, mr->alias->size)) {
                /* The alias is included in its entirety.  Use it as
                 * the "real" root, so that we can share more FlatViews.
                 */
                mr = mr->alias;
                continue;
            }
        } else if (!mr->terminates) {
            unsigned int found = 0;
            MemoryRegion *child, *next = NULL;
            QTAILQ_FOREACH(child, &mr->subregions, subregions_link) {
                if (child->enabled) {
                    if (++found > 1) {
                        next = NULL;
                        break;
                    }
                    if (!child->addr && int128_ge(mr->size, child->size)) {
                        /* A child is included in its entirety.  If it's the only
                         * enabled one, use it in the hope of finding an alias down the
                         * way. This will also let us share FlatViews.
                         */
                        next = child;
                    }
                }
            }
            if (found == 0) {
                return NULL;
            }
            if (next) {
                mr = next;
                continue;
            }
        }

        return mr;
    }

    return NULL;
}

```


```cpp
/* Render a memory topology into a list of disjoint absolute ranges. */
static FlatView *generate_memory_topology(MemoryRegion *mr)
{
    int i;
    FlatView *view;

    view = flatview_new(mr);

    if (mr) {
        render_memory_region(view, mr, int128_zero(),
                             addrrange_make(int128_zero(), int128_2_64()),
                             false, false);
    }
    flatview_simplify(view);

    view->dispatch = address_space_dispatch_new(view);
    for (i = 0; i < view->nr; i++) {
        MemoryRegionSection mrs =
            section_from_flat_range(&view->ranges[i], view);
        flatview_add_to_dispatch(view, &mrs);
    }
    address_space_dispatch_compact(view->dispatch);
    g_hash_table_replace(flat_views, mr, view);

    return view;
}
```

```cpp
static void address_space_set_flatview(AddressSpace *as)
{
    FlatView *old_view = address_space_to_flatview(as);
    MemoryRegion *physmr = memory_region_get_flatview_root(as->root);
    FlatView *new_view = g_hash_table_lookup(flat_views, physmr);

    assert(new_view);

    if (old_view == new_view) {
        return;
    }

    if (old_view) {
        flatview_ref(old_view);
    }

    flatview_ref(new_view);

    if (!QTAILQ_EMPTY(&as->listeners)) {
        FlatView tmpview = { .nr = 0 }, *old_view2 = old_view;

        if (!old_view2) {
            old_view2 = &tmpview;
        }
        address_space_update_topology_pass(as, old_view2, new_view, false);
        address_space_update_topology_pass(as, old_view2, new_view, true);
    }

    /* Writes are protected by the BQL.  */
    qatomic_rcu_set(&as->current_map, new_view);
    if (old_view) {
        flatview_unref(old_view);
    }

    /* Note that all the old MemoryRegions are still alive up to this
     * point.  This relieves most MemoryListeners from the need to
     * ref/unref the MemoryRegions they get---unless they use them
     * outside the iothread mutex, in which case precise reference
     * counting is necessary.
     */
    if (old_view) {
        flatview_unref(old_view);
    }
}
```

Each AddressSpace has dedicated listener (please refer to [[]]), so it will 
invoke the address_space_update_topology_pass function.

```cpp
static void address_space_update_topology_pass(AddressSpace *as,
                                               const FlatView *old_view,
                                               const FlatView *new_view,
                                               bool adding)
{
    unsigned iold, inew;
    FlatRange *frold, *frnew;
......
        } else {
            /* In new */

            if (adding) {
                MEMORY_LISTENER_UPDATE_REGION(frnew, as, Forward, region_add);
                flat_range_coalesced_io_add(frnew, as);
            }

            ++inew;
        }
    }
}
```

```cpp
/* No need to ref/unref .mr, the FlatRange keeps it alive.  */
#define MEMORY_LISTENER_UPDATE_REGION(fr, as, dir, callback, _args...)  \
    do {                                                                \
        MemoryRegionSection mrs = section_from_flat_range(fr,           \
                address_space_to_flatview(as));                         \
        MEMORY_LISTENER_CALL(as, callback, dir, &mrs, ##_args);         \
    } while(0)

#define MEMORY_LISTENER_CALL(_as, _callback, _direction, _section, _args...) \
    do {                                                                \
        MemoryListener *_listener;                                      \
                                                                        \
        switch (_direction) {                                           \
        case Forward:                                                   \
            QTAILQ_FOREACH(_listener, &(_as)->listeners, link_as) {     \
                if (_listener->_callback) {                             \
                    _listener->_callback(_listener, _section, ##_args); \
                }                                                       \
            }                                                           \
            break;                                                      \
        case Reverse:                                                   \
            QTAILQ_FOREACH_REVERSE(_listener, &(_as)->listeners, link_as) { \
                if (_listener->_callback) {                             \
                    _listener->_callback(_listener, _section, ##_args); \
                }                                                       \
            }                                                           \
            break;                                                      \
        default:                                                        \
            abort();                                                    \
        }                                                               \
    } while (0)
```


