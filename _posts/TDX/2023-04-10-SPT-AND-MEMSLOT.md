---
layout: post
title: "Shadow Page Table (SPT) and MEMSLOT"
categories: [Confidential Computing, Intel TDX, KVM, QEMU] 
---
## Shadow Page Table (SPT)
Before the introduction of TDP, shadow paging has been utilized to translate
**GPA to HPA**. The KVM module utilize a unified concept to abstract the 
structure managing this translation (GPA->HPA), called **Shadow Page Table (SPT)**. 
Although it reminds of shadow paging, the emulated page table based 
translation before the invention TDP, now it represents the table handling 
GPA->HPA translation regardless of the implementation behind. KVM utilizes the
term Two Dimensional Paging (TDP) to distinguish EPT based translation 
(hardware) from shadow page table based translation (software-emulation). This
terminology is quite confusing, but allow the TDP implementation to fit into the
code base previously implemented for shadow paging. Each entry of SPT is called 
Shadow Page Table Entry (SPTE).

### Struct kvm_mmu_page
EPT consists of 4 different levels, the top level is Level-4 (PML4 Table), and
then Level-3 (PDPT), Level-2 (PDT), Level-1 (PT) in turn. Each page table page,
regardless of the levels, are represented by **kvm_mmu_page** in the KVM. 

```cpp
struct kvm_mmu_page {
        struct list_head link;
        struct hlist_node hash_link;
        
        bool tdp_mmu_page;
        bool unsync;
        u8 mmu_valid_gen;
        bool lpage_disallowed; /* Can't be replaced by an equiv large page */

        /*
         * The following two entries are used to key the shadow page in the
         * hash table.
         */
        union kvm_mmu_page_role role;
        gfn_t gfn;
        gfn_t gfn_stolen_bits;

        u64 *spt;
        /* hold the gfn of each spte inside spt */
        gfn_t *gfns;
        /* associated private shadow page, e.g. SEPT page */
        void *private_sp;
        /* Currently serving as active root */
        union {
                int root_count;
                refcount_t tdp_mmu_root_count;
        };
        unsigned int unsync_children;
        struct kvm_rmap_head parent_ptes; /* rmap pointers to parent sptes */
        DECLARE_BITMAP(unsync_child_bitmap, 512);

        struct list_head lpage_disallowed_link;

        /* Number of writes since the last time traversal visited this page.  */
        atomic_t write_flooding_count;

        /* Used for freeing the page asynchronously if it is a TDP MMU page. */
        struct rcu_head rcu_head;
};
```

Main job of each level of EPT is storing physical address of next level EPT, and 
the spt member field is used for this purpose. However, kvm_mmu_page structure 
consists of lots of different member fields which are not ISA specific. These 
additional information describes SPT used for describing different EPT levels. 

```cpp
union kvm_mmu_page_role {
        u32 word;
        struct {
                unsigned level:4;
                unsigned gpte_is_8_bytes:1;
                unsigned quadrant:2;
                unsigned direct:1;
                unsigned access:3;
                unsigned invalid:1;
                unsigned efer_nx:1;
                unsigned cr0_wp:1;
                unsigned smep_andnot_wp:1;
                unsigned smap_andnot_wp:1;
                unsigned ad_disabled:1;
                unsigned guest_mode:1;
                unsigned :6;

                /*
                 * This is left at the top of the word so that
                 * kvm_memslots_for_spte_role can extract it with a
                 * simple shift.  While there is room, give it a whole
                 * byte so it is also faster to load it from memory.
                 */
                unsigned smm:8;
        };
};
```
kvm_mmu_page_role tracks the properties of a shadow page such as the level of 
page it belongs to.

## SPT Initialization 
### SPT is initialized when VCPU first enter the guest
```cpp
static int vcpu_enter_guest(struct kvm_vcpu *vcpu)
{
......
        r = kvm_mmu_reload(vcpu);
        if (unlikely(r)) {
                goto cancel_injection;
        }

        preempt_disable();

        static_call(kvm_x86_prepare_guest_switch)(vcpu);
```

```cpp
static inline int kvm_mmu_reload(struct kvm_vcpu *vcpu)
{       
        if (likely(vcpu->arch.mmu->root_hpa != INVALID_PAGE))
                return 0;

        return kvm_mmu_load(vcpu);
}
```

kvm_mmu_reload function invokes kvm_mmu_load only when root_hpa was initialized 
as IVALID_PAGE, which means the SPT has not been actually initialized yet. 

```cpp
int kvm_mmu_load(struct kvm_vcpu *vcpu)
{
        int r;

        r = mmu_topup_memory_caches(vcpu, !vcpu->arch.mmu->direct_map);
        if (r)
                goto out;       
        r = mmu_alloc_special_roots(vcpu);
        if (r)
                goto out;
        if (vcpu->arch.mmu->direct_map)
                r = mmu_alloc_direct_roots(vcpu);
        else
                r = mmu_alloc_shadow_roots(vcpu);
        if (r)
                goto out;    

        kvm_mmu_sync_roots(vcpu);
                                
        kvm_mmu_load_pgd(vcpu);
        static_call(kvm_x86_tlb_flush_current)(vcpu);
out: 
        return r;
}
```

If MMU utilize the TDP, the **direct_map** field is initialized as true by the 
init_kvm_tdp_mmu function, and invokes mmu_alloc_direct_roots function. 


### Allocate SPT root page table 
```cpp
static int mmu_alloc_direct_roots(struct kvm_vcpu *vcpu)
{
4059         if (is_tdp_mmu_enabled(vcpu->kvm)) {
4060                 root = kvm_tdp_mmu_get_vcpu_root_hpa(vcpu);
4061                 mmu->root_hpa = root;
4062         } else if (shadow_root_level >= PT64_ROOT_4LEVEL) {
4063                 if (gfn_shared && !VALID_PAGE(vcpu->arch.mmu->private_root_hpa)) {
4064                         root = mmu_alloc_root(vcpu, 0, 0, 0, shadow_root_level, true);
4065                         vcpu->arch.mmu->private_root_hpa = root;
4066                 }
4067                 root = mmu_alloc_root(vcpu, 0, gfn_shared, 0, shadow_root_level, true);
4068                 vcpu->arch.mmu->root_hpa = root;
```

Note that root_hpa has been initialized as INVALID_PAGE, which makes the 
is_tdp_mmu_enabled function return false. Also we assume that current platform
supports 4 or 5 level page tables, so it will execute the first else if block. 
gfn_shared is the bit for distinguishing shared page table from private for 
Intel TDX. Because TDX requires two different page tables, one for shared and 
the other for private, it generates two page table through mmu_alloc_root. Note
that the generated root page is stored in different member fields of the mmu,
**private_root_hpa and root_hpa**. From now on, is_tdp_mmu_enabled will return 
true because all required fields are initialized. 

```cpp
4032 static hpa_t mmu_alloc_root(struct kvm_vcpu *vcpu, gfn_t gfn,
4033                             gfn_t gfn_stolen_bits, gva_t gva, u8 level,
4034                             bool direct)
4035 {
4036         struct kvm_mmu_page *sp;
4037 
4038         sp = __kvm_mmu_get_page(vcpu, gfn, gfn_stolen_bits, gva, level, direct,
4039                                 ACC_ALL);
4040         ++sp->root_count;
4041 
4042         return __pa(sp->spt);
4043 }
```

Note that gfn field is set as zero. Also the root_count variable is increased,
which keep tracks of how many hardware registers (guest cr3 or pdptrs) are point
at this root page. 

```cpp
2475 static struct kvm_mmu_page *__kvm_mmu_get_page(struct kvm_vcpu *vcpu,
2476                                                gfn_t gfn,
2477                                                gfn_t gfn_stolen_bits,
2478                                                gva_t gaddr,
2479                                                unsigned int level,
2480                                                int direct,
2481                                                unsigned int access)
2482 {
......
2559         sp = kvm_mmu_alloc_page(vcpu, direct,
2560                                 is_private_gfn(vcpu, gfn_stolen_bits));
......
2577         return sp;
2578 }
```

### Allocate SPT page table 
No matter what level it is, whether it is root or the lower level non-leaf SPTE,
the SPT table is a instance of kvm_mmu_page struct. Therefore, the 
kvm_mmu_alloc_page function generates new kvm_mmu_page object and sets up its 
member fields. 

```cpp
2138 static struct kvm_mmu_page *kvm_mmu_alloc_page(struct kvm_vcpu *vcpu,
2139                                                int direct, bool private)
2140 {
2141         struct kvm_mmu_page *sp;
2142         
2143         sp = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_page_header_cache);
2144         sp->spt = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_shadow_page_cache);
2145         if (!direct) 
2146                 sp->gfns = kvm_mmu_memory_cache_alloc(&vcpu->arch.mmu_gfn_array_cache);
2147         set_page_private(virt_to_page(sp->spt), (unsigned long)sp);
2148                         
2149         /*
2150          * active_mmu_pages must be a FIFO list, as kvm_zap_obsolete_pages()
2151          * depends on valid pages being added to the head of the list.  See
2152          * comments in kvm_zap_obsolete_pages().
2153          */
2154         sp->mmu_valid_gen = vcpu->kvm->arch.mmu_valid_gen;
2155         if (private)
2156                 list_add(&sp->link, &vcpu->kvm->arch.private_mmu_pages);
2157         else
2158                 list_add(&sp->link, &vcpu->kvm->arch.active_mmu_pages);
2159         kvm_mod_used_mmu_pages(vcpu->kvm, +1);
2160         return sp;                           
2161 }   
```

There are two important memory allocations, one for shadow page structure (sp),
and the other for shadow page table entries (sp->spt).

>The page pointed to by spt will have its page->private pointing back at the 
>shadow page structure

After memories are allocated, the set_page_private macro makes the private field
of page(sp->spt) points to the shadow page structure, which is kvm_mmu_page *sp.
Therefore, when sp->spt can be accessible (as a result of EPT walking), the 
kvm_mmu_page pointing to that SPTE can be accessible through the private field. 

Note that this is not relevant to shared/private concept of Intel TDX for SPT.
Also, the KVM maintains the list of SPT, kvm->arch.private_mmu_pages
and kvm->arch.active_mmu_pages for private and shared SPT. Based on the SPT type,
generated SPT will be stored in the different lists. 

```cpp
2475 static struct kvm_mmu_page *__kvm_mmu_get_page(struct kvm_vcpu *vcpu,      
2476                                                gfn_t gfn,                  
2477                                                gfn_t gfn_stolen_bits,      
2478                                                gva_t gaddr,                
2479                                                unsigned int level,         
2480                                                int direct,                 
2481                                                unsigned int access)
......
2562         sp->gfn = gfn;                                                     
2563         sp->gfn_stolen_bits = gfn_stolen_bits;                             
2564         sp->role = role;                                                   
2565         hlist_add_head(&sp->hash_link, sp_list);                           
2566         if (!direct) {                                                     
2567                 account_shadowed(vcpu->kvm, sp);                           
2568                 if (level == PG_LEVEL_4K && rmap_write_protect(vcpu, gfn)) 
2569                         kvm_flush_remote_tlbs_with_address(vcpu->kvm, gfn, 1);
2570         }                                                                  
2571         trace_kvm_mmu_get_page(sp, true);                                  
2572 out:                                                                       
2573         kvm_mmu_commit_zap_page(vcpu->kvm, &invalid_list);                 
2574                                                                            
2575         if (collisions > vcpu->kvm->stat.max_mmu_page_hash_collisions)     
2576                 vcpu->kvm->stat.max_mmu_page_hash_collisions = collisions; 
2577         return sp;    
```
The __kvm_mmu_get_page function initializes some member fields of the generated 
SPT, flush out some tlbs for synchronization, and return the generates spt. The
spt is returned further up to mmu_alloc_direct_roots function, and its physical 
address is stored to either root_hpa or private_root_hpa.



### VMCS setting for SPT
```cpp
static inline void kvm_mmu_load_pgd(struct kvm_vcpu *vcpu)
{       
        u64 root_hpa = vcpu->arch.mmu->root_hpa;
        
        if (!VALID_PAGE(root_hpa))
                return;

        static_call(kvm_x86_load_mmu_pgd)(vcpu, root_hpa,
                                          vcpu->arch.mmu->shadow_root_level);
}    
```


```cpp
static void vt_load_mmu_pgd(struct kvm_vcpu *vcpu, hpa_t root_hpa,
                            int pgd_level)
{
        if (is_td_vcpu(vcpu))
                return tdx_load_mmu_pgd(vcpu, root_hpa, pgd_level);

        vmx_load_mmu_pgd(vcpu, root_hpa, pgd_level);
}
```

```cpp
static void vmx_load_mmu_pgd(struct kvm_vcpu *vcpu, hpa_t root_hpa,
                             int root_level)
{
        struct kvm *kvm = vcpu->kvm;
        bool update_guest_cr3 = true;
        unsigned long guest_cr3;
        u64 eptp;

        if (enable_ept) {
                eptp = construct_eptp(vcpu, root_hpa, root_level);
                vmcs_write64(EPT_POINTER, eptp);

                hv_track_root_tdp(vcpu, root_hpa);

                if (!enable_unrestricted_guest && !is_paging(vcpu))
                        guest_cr3 = to_kvm_vmx(kvm)->ept_identity_map_addr;
                else if (test_bit(VCPU_EXREG_CR3, (ulong *)&vcpu->arch.regs_avail))
                        guest_cr3 = vcpu->arch.cr3;
                else /* vmcs01.GUEST_CR3 is already up-to-date. */
                        update_guest_cr3 = false;
                vmx_ept_load_pdptrs(vcpu);
        } else {
                guest_cr3 = root_hpa | kvm_get_active_pcid(vcpu);
        }

        if (update_guest_cr3)
                vmcs_writel(GUEST_CR3, guest_cr3);
}
```

Through vmcx_write64 macro, it writes eptp pointer (spt root) to the EPTP field
of the VMCS structure associated with current VCPU. However, still the only root
SPT address has been set, and the content has not been filled out, which means 
the running VM will generates fault. 


## HVA and memslot
Another important concept related with KVM and its memory management is HVA and
memslot which can be considered as a one level page table mapping **GPA to HVA.**

>Guest memory (gpa) is part of the user address space of the process that is
>using kvm.  Userspace defines the translation between guest addresses and user
>addresses (gpa->hva); note that two gpas may alias to the same hva, but not
>vice versa.
>These hvas may be backed using any method available to the host: anonymous
>memory, file backed memory, and device memory.  Memory might be paged by the
>host at any time.

As described in the KVM MMU documentation, the VM instance utilize the memory 
provided by the user process that is using KVM. Therefore, the memory KVM gets 
are part of the donor's user address space. However, the EPT page table 
translates the GPA to HPA not GPA to HVA. Therefore, the KVM should require 
correct mapping for EPT page tables based on GPA -> HVA translation. For example,
when VMEXIT happens because the GPA is not mapped to any HPA (EPT violation),
then KVM walks the page table of the user process that is using KVM to retrieve
the HPA associated with HVA that is used for mapping GPA. After the page walks,
it sets up EPT page tables so that the GPA can be directly mapped to correct 
HPA which is mapped to GVA. 

Therefore, the synchronization between EPT and user process table on host side 
is very important. To keep the synchronization, if previous HVA->HPA mapping
changes and remapped to another HPA, then **KVM will get notified by the host 
kernel** that the HVA has been unmapped. KVM will find and unmap the 
corresponding GPA (again via memslots) to HPA translations and modifies EPT to 
map GPA to new HPA remapped to HVA. 

>If there is no memslot, KVM will exit to userspace on the EPT violation,
>with some information about what GPA the guest was accessing.  This is how
>emulated MMIO is implemented, e.g. userspace intentionally doesn't back a
>GPA with a memslot so that it can trap guest accesses to said GPA for the
>purpose of emulating a device.
https://lists.gnu.org/archive/html/qemu-devel/2020-10/msg03532.html

### Memslot data structures
```cpp
struct kvm_memslots {
        u64 generation;
        /* The mapping table from slot id to the index in memslots[]. */
        short id_to_index[KVM_MEM_SLOTS_NUM];
        atomic_t last_used_slot;
        int used_slots;
        struct kvm_memory_slot memslots[];
};
```

```cpp
struct kvm_memory_slot {
        struct hlist_node id_node[2];
        struct interval_tree_node hva_node[2];
        struct rb_node gfn_node[2];
        gfn_t base_gfn;
        unsigned long npages;
        unsigned long *dirty_bitmap;
        struct kvm_arch_memory_slot arch;
        unsigned long userspace_addr;
        u32 flags;
        short id;
        u16 as_id;
        struct file *private_file;
        loff_t private_offset;
        struct memfile_notifier notifier;
        struct kvm *kvm;
};
```

