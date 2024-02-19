# KVM TDX creation flow
In addition to KVM normal flow, new TDX ioctls need to be called. The control flow
looks like as follows (from virt/kvm/intel-tdx.rst).

1. system wide capability check
  - KVM_TDX_CAPABILITIES: query if TDX is supported on the platform.
  - KVM_CAP_xxx: check other KVM extensions same to normal KVM case.

2. creating VM
  - KVM_CREATE_VM
  - KVM_TDX_INIT_VM: pass TDX specific VM parameters.

3. creating VCPU
  - KVM_CREATE_VCPU
  - KVM_TDX_INIT_VCPU: pass TDX specific VCPU parameters.

4. initializing guest memory
  - allocate guest memory and initialize page same to normal KVM case
    In TDX case, parse and load TDVF into guest memory in addition.
  - KVM_TDX_INIT_MEM_REGION to add and measure guest pages.
    If the pages has contents above, those pages need to be added.
    Otherwise the contents will be lost and guest sees zero pages.
  - KVM_TDX_FINALIAZE_VM: Finalize VM and measurement
    This must be after KVM_TDX_INIT_MEM_REGION.

5. run vcpu



## Step1: System wide capability check
TDX features are initialized during the original KVM initialization routine. 
Specifically, through the KVM_TDX_CAPABILITIES ioctl call to the KVM kernel 
module, it can check the capabilities of TDX during the initialization.

### KVM Initialization on QEMU side
**accel/kvm/kvm-all.c**
```cpp
2356 static int kvm_init(MachineState *ms)
2357 {
2358     MachineClass *mc = MACHINE_GET_CLASS(ms);
......
2636     kvm_state = s;
2637 
2638     ret = kvm_arch_init(ms, s);
......
```

```cpp
2424 int kvm_arch_init(MachineState *ms, KVMState *s)
2425 {
2426     uint64_t identity_base = 0xfffbc000;
2427     uint64_t shadow_mem;
2428     int ret;
2429     struct utsname utsname;
2430     Error *local_err = NULL;
2431 
2432     /*
2433      * Initialize SEV context, if required
2434      *
2435      * If no memory encryption is requested (ms->cgs == NULL) this is
2436      * a no-op.
2437      *
2438      * It's also a no-op if a non-SEV confidential guest support
2439      * mechanism is selected.  SEV is the only mechanism available to
2440      * select on x86 at present, so this doesn't arise, but if new
2441      * mechanisms are supported in future (e.g. TDX), they'll need
2442      * their own initialization either here or elsewhere.
2443      */
2444     ret = sev_kvm_init(ms->cgs, &local_err);
2445     if (ret < 0) {
2446         error_report_err(local_err);
2447         return ret;
2448     }
2449 
2450     ret = tdx_kvm_init(ms->cgs, s, &local_err);
2451     if (ret < 0) {
2452         error_report_err(local_err);
2453         return ret;
2454     }
......
```

Because TDX is architecture specific feature, it will be initialized through the
kvm_arch_init function.


```cpp
 278 int tdx_kvm_init(ConfidentialGuestSupport *cgs, KVMState *s, Error **errp)
 279 {
 280     struct kvm_tdx_capabilities *caps;
 281     uint32_t nr_cpuid_configs;
 282     TdxGuest *tdx = (TdxGuest *)object_dynamic_cast(OBJECT(cgs),
 283                                                     TYPE_TDX_GUEST);
 284     if (!tdx) {
 285         return 0;
 286     }
 287 
 288     caps = NULL;
 289     nr_cpuid_configs = 8;
 290     while (true) {
 291         int r;
 292         caps = g_realloc(caps, sizeof(*caps) +
 293                         sizeof(*caps->cpuid_configs) * nr_cpuid_configs);
 294         caps->nr_cpuid_configs = nr_cpuid_configs;
 295         r = tdx_ioctl(KVM_TDX_CAPABILITIES, 0, caps);
 296         if (r == -E2BIG) {
 297             nr_cpuid_configs *= 2;
 298             continue;
 299         }
 300         break;
 301     }
 302     tdx_caps = caps;
 303 
 304     if (!kvm_enable_x2apic()) {
 305         error_report("Failed to enable x2apic in KVM");
 306         exit(1);
 307     }
 308 
 309     qemu_add_machine_init_done_late_notifier(&tdx_machine_done_late_notify);
 310 
 311     if (tdx->debug &&
 312         kvm_vm_check_extension(s, KVM_CAP_ENCRYPT_MEMORY_DEBUG)) {
 313         kvm_setup_set_memory_region_debug_ops(s,
 314                                               kvm_encrypted_guest_set_memory_region_debug_ops);
 315         set_encrypted_memory_debug_ops();
 316     }
 317 
 318     return 0;
 319 }
```

Through the invocation of tdx_ioctl, it asks the tdx capabilities to the **KVM
module**.

### tdx_ioctl -> KVM kernel module function
Most TDX related functions are handled by the tdx_ioctl function.

```cpp
 170 static int __tdx_ioctl(void *state, int ioctl_no, const char *ioctl_name,
 171                         __u32 metadata, void *data)
 172 {
 173     struct kvm_tdx_cmd tdx_cmd;
 174     int r;
 175 
 176     memset(&tdx_cmd, 0x0, sizeof(tdx_cmd));
 177 
 178     tdx_cmd.id = ioctl_no;
 179     tdx_cmd.metadata = metadata;
 180     tdx_cmd.data = (__u64)(unsigned long)data;
 181 
 182     if (ioctl_no == KVM_TDX_INIT_VCPU) {
 183         r = kvm_vcpu_ioctl(state, KVM_MEMORY_ENCRYPT_OP, &tdx_cmd);
 184     } else {
 185         r = kvm_vm_ioctl(state, KVM_MEMORY_ENCRYPT_OP, &tdx_cmd);
 186     }
 187 
 188     /*
 189      * REVERTME: Workaround for incompatible ABI change.  KVM_TDX_CAPABILITIES
 190      * was changed from system ioctl to VM ioctl.  Make KVM_TDX_CAPABILITIES
 191      * work with old ABI.
 192      */
 193     if (r && r != -E2BIG && ioctl_no == KVM_TDX_CAPABILITIES) {
 194         r = kvm_ioctl(state, KVM_MEMORY_ENCRYPT_OP, &tdx_cmd);
 195     }
 196     if (ioctl_no == KVM_TDX_CAPABILITIES && r == -E2BIG)
 197         return r;
 198 
 199     if (r) {
 200         error_report("%s failed: %s", ioctl_name, strerror(-r));
 201         exit(1);
 202     }
 203     return 0;
 204 }
```

Because KVM manages multiple file descriptors to provide different services to 
manage VMs, based on the TDX ioctl number, it invokes different functions (i.e.,
kv_vcpu_ioctl, kvm_vm_ioctl, and kvm_ioctl) to select proper file descriptors. 
Also remember that the TDX related KVM functions are serviced as sub-functions
of **KVM_MEMORY_ENCRYPT_OP.**

```cpp
3085 int kvm_ioctl(KVMState *s, int type, ...)
3086 {
3087     int ret;
3088     void *arg;
3089     va_list ap;
3090 
3091     va_start(ap, type);
3092     arg = va_arg(ap, void *);
3093     va_end(ap);
3094 
3095     trace_kvm_ioctl(type, arg);
3096     ret = ioctl(s->fd, type, arg);
3097     if (ret == -1) {
3098         ret = -errno;
3099     }
3100     return ret;
3101 }
3102 
3103 int kvm_vm_ioctl(KVMState *s, int type, ...)
3104 {
3105     int ret;
3106     void *arg;
3107     va_list ap;
3108 
3109     va_start(ap, type);
3110     arg = va_arg(ap, void *);
3111     va_end(ap);
3112 
3113     trace_kvm_vm_ioctl(type, arg);
3114     ret = ioctl(s->vmfd, type, arg);
3115     if (ret == -1) {
3116         ret = -errno;
3117     }
3118     return ret;
3119 }
3120 
3121 int kvm_vcpu_ioctl(CPUState *cpu, int type, ...)
3122 {
3123     int ret;
3124     void *arg;
3125     va_list ap;
3126 
3127     va_start(ap, type);
3128     arg = va_arg(ap, void *);
3129     va_end(ap);
3130 
3131     trace_kvm_vcpu_ioctl(cpu->cpu_index, type, arg);
3132     ret = ioctl(cpu->kvm_fd, type, arg);
3133     if (ret == -1) {
3134         ret = -errno;
3135     }
3136     return ret;
3137 }
```

## Step2: Creating VM
### KVM_CREATE_VM
To understand when the KVM_CREATE_VM ioctl is invoked, we should understand how
the QEMU handles the VM instantiation. 

**accel/kvm/kvm-all.c**
```cpp
3740 static void kvm_accel_instance_init(Object *obj)
3741 {
3742     KVMState *s = KVM_STATE(obj);
3743 
3744     s->fd = -1;
3745     s->vmfd = -1;
3746     s->kvm_shadow_mem = -1;
3747     s->kernel_irqchip_allowed = true;
3748     s->kernel_irqchip_split = ON_OFF_AUTO_AUTO;
3749     /* KVM dirty ring is by default off */
3750     s->kvm_dirty_ring_size = 0;
3751 }
3752
3753 static void kvm_accel_class_init(ObjectClass *oc, void *data)
3754 {
3755     AccelClass *ac = ACCEL_CLASS(oc);
3756     ac->name = "KVM";
3757     ac->init_machine = kvm_init;
3758     ac->has_memory = kvm_accel_has_memory;
3759     ac->allowed = &kvm_allowed;
3760 
3761     object_class_property_add(oc, "kernel-irqchip", "on|off|split",
3762         NULL, kvm_set_kernel_irqchip,
3763         NULL, NULL);
3764     object_class_property_set_description(oc, "kernel-irqchip",
3765         "Configure KVM in-kernel irqchip");
3766 
3767     object_class_property_add(oc, "kvm-shadow-mem", "int",
3768         kvm_get_kvm_shadow_mem, kvm_set_kvm_shadow_mem,
3769         NULL, NULL);
3770     object_class_property_set_description(oc, "kvm-shadow-mem",
3771         "KVM shadow MMU size");
3772 
3773     object_class_property_add(oc, "dirty-ring-size", "uint32",
3774         kvm_get_dirty_ring_size, kvm_set_dirty_ring_size,
3775         NULL, NULL);
3776     object_class_property_set_description(oc, "dirty-ring-size",
3777         "Size of KVM dirty page ring buffer (default: 0, i.e. use bitmap)");
3778 }
3779 
3780 static const TypeInfo kvm_accel_type = {
3781     .name = TYPE_KVM_ACCEL,
3782     .parent = TYPE_ACCEL,
3783     .instance_init = kvm_accel_instance_init,
3784     .class_init = kvm_accel_class_init,
3785     .instance_size = sizeof(KVMState),
3786 };
3787 
3788 static void kvm_type_init(void)
3789 {
3790     type_register_static(&kvm_accel_type);
3791 }
3792 
3793 type_init(kvm_type_init);
```

Through this device initialization, whenever the VM needs to be generated, it 
invokes the **kvm_init** function. 

```cpp
2356 static int kvm_init(MachineState *ms)
2357 {
2358     MachineClass *mc = MACHINE_GET_CLASS(ms);
2359     static const char upgrade_note[] =
2360         "Please upgrade to at least kernel 2.6.29 or recent kvm-kmod\n"
2361         "(see http://sourceforge.net/projects/kvm).\n";
2362     struct {
2363         const char *name;
2364         int num;
2365     } num_cpus[] = {
2366         { "SMP",          ms->smp.cpus },
2367         { "hotpluggable", ms->smp.max_cpus },
2368         { NULL, }
2369     }, *nc = num_cpus;
2370     int soft_vcpus_limit, hard_vcpus_limit;
2371     KVMState *s;
2372     const KVMCapabilityInfo *missing_cap;
2373     int ret;
2374     int type = 0;
2375     uint64_t dirty_log_manual_caps;
2376 
2377     qemu_mutex_init(&kml_slots_lock);
2378 
2379     s = KVM_STATE(ms->accelerator);
......
2395     s->fd = qemu_open_old("/dev/kvm", O_RDWR);
2396     if (s->fd == -1) {
2397         fprintf(stderr, "Could not access KVM kernel module: %m\n");
2398         ret = -errno;
2399         goto err;
2400     }
2401 
2402     ret = kvm_ioctl(s, KVM_GET_API_VERSION, 0);
......
2440     do {
2441         ret = kvm_ioctl(s, KVM_CREATE_VM, type);
2442     } while (ret == -EINTR);
......
2470     s->vmfd = ret;
......
```

### KVM_TDX_INIT_VM: pass TDX specific VM parameters.
**target/i386/kvm/tdx.c**
```cpp
 824 void tdx_pre_create_vcpu(CPUState *cpu)
 825 {
......
 839     MachineState *ms = MACHINE(qdev_get_machine());
 840     X86CPU *x86cpu = X86_CPU(cpu);
 841     CPUX86State *env = &x86cpu->env;
 842     TdxGuest *tdx = (TdxGuest *)object_dynamic_cast(OBJECT(ms->cgs),
 843                                                     TYPE_TDX_GUEST);
 844     struct kvm_tdx_init_vm init_vm;
......
 880     init_vm.max_vcpus = ms->smp.cpus;
 881     init_vm.tsc_khz = env->tsc_khz;
 882     init_vm.attributes = 0;
 883     init_vm.attributes |= tdx->debug ? TDX1_TD_ATTRIBUTE_DEBUG : 0;
 884     init_vm.attributes |= tdx->sept_ve_disable ? TDX1_TD_ATTRIBUTE_SEPT_VE_DISABLE : 0;
 885     init_vm.attributes |= (env->features[FEAT_7_0_ECX] & CPUID_7_0_ECX_PKS) ?
 886         TDX1_TD_ATTRIBUTE_PKS : 0;
 887     init_vm.attributes |= x86cpu->enable_pmu ? TDX1_TD_ATTRIBUTE_PERFMON : 0;
 888                    
 889     QEMU_BUILD_BUG_ON(sizeof(init_vm.mrconfigid) != sizeof(tdx->mrconfigid));
 890     memcpy(init_vm.mrconfigid, tdx->mrconfigid, sizeof(init_vm.mrconfigid));
 891     QEMU_BUILD_BUG_ON(sizeof(init_vm.mrowner) != sizeof(tdx->mrowner));
 892     memcpy(init_vm.mrowner, tdx->mrowner, sizeof(init_vm.mrowner));
 893     QEMU_BUILD_BUG_ON(sizeof(init_vm.mrownerconfig) !=
 894                       sizeof(tdx->mrownerconfig));
 895     memcpy(init_vm.mrownerconfig, tdx->mrownerconfig,
 896            sizeof(init_vm.mrownerconfig));
 897 
 898     memset(init_vm.reserved, 0, sizeof(init_vm.reserved));
 899 
 900     init_vm.cpuid = (__u64)(&cpuid_data);
 901     tdx_ioctl(KVM_TDX_INIT_VM, 0, &init_vm);
```

```cpp
568 struct kvm_tdx_init_vm {
569         __u32 max_vcpus;
570         __u32 tsc_khz;
571         __u64 attributes;
572         __u64 cpuid;
573         __u64 mrconfigid[6];    /* sha384 digest */
574         __u64 mrowner[6];       /* sha384 digest */
575         __u64 mrownerconfig[6]; /* sha348 digest */
576         __u64 reserved[43];     /* must be zero for future extensibility */
577 };   
```

As shown in the above code, TDX VM instance is initialized during the VCPU initialization through 
the ioctl, KVM_TDX_INIT_VM. All information required to initialize the TDVM is provided through 
the TdxGuest such as the mrconfig, mrowner, &c. 

## Step3: Creating VCPU
### KVM_CREATE_VCPU
**accel/kvm/kvm-all.c**
```cpp
 486 int kvm_init_vcpu(CPUState *cpu, Error **errp)
 487 {
 488     KVMState *s = kvm_state;
 489     long mmap_size;
 490     int ret;
 491 
 492     trace_kvm_init_vcpu(cpu->cpu_index, kvm_arch_vcpu_id(cpu));
 493 
 494     /*
 495      * tdx_pre_create_vcpu() may call cpu_x86_cpuid(). It in turn may call
 496      * kvm_vm_ioctl(). Set cpu->kvm_state in advance to avoid NULL pointer
 497      * deference.
 498      */
 499     cpu->kvm_state = s;
 500     tdx_pre_create_vcpu(cpu);
 501     ret = kvm_get_vcpu(s, kvm_arch_vcpu_id(cpu));
 502     if (ret < 0) {
 503         error_setg_errno(errp, -ret, "kvm_init_vcpu: kvm_get_vcpu failed (%lu)",
 504                          kvm_arch_vcpu_id(cpu));
 505         cpu->kvm_state = NULL;
 506         goto err;
 507     }
 508 
 509     cpu->kvm_fd = ret;
```

```cpp
 468 static int kvm_get_vcpu(KVMState *s, unsigned long vcpu_id)
 469 {
 470     struct KVMParkedVcpu *cpu;
 471 
 472     QLIST_FOREACH(cpu, &s->kvm_parked_vcpus, node) {
 473         if (cpu->vcpu_id == vcpu_id) {
 474             int kvm_fd;
 475 
 476             QLIST_REMOVE(cpu, node);
 477             kvm_fd = cpu->kvm_fd;
 478             g_free(cpu);
 479             return kvm_fd;
 480         }
 481     }
 482 
 483     return kvm_vm_ioctl(s, KVM_CREATE_VCPU, (void *)vcpu_id);
 484 }
```

### KVM_TDX_INIT_VCPU: pass TDX specific VCPU parameters.
**target/i386/kvm/tdx.c**
```cpp
 907 void tdx_post_init_vcpu(CPUState *cpu)
 908 {                  
 909     MachineState *ms = MACHINE(qdev_get_machine());
 910     TdxGuest *tdx = (TdxGuest *)object_dynamic_cast(OBJECT(ms->cgs),
 911                                                     TYPE_TDX_GUEST);
 912     TdxFirmwareEntry *hob;
 913 
 914     if (!tdx) {
 915         return;
 916     }
 917 
 918     hob = tdx_get_hob_entry(tdx);
 919     _tdx_ioctl(cpu, KVM_TDX_INIT_VCPU, 0, (void *)hob->address);
 920    
 921     apic_force_x2apic(X86_CPU(cpu)->apic_state);
 922 }  
```

**target/i386/kvm/kvm.c**
```cpp
4426 int kvm_arch_put_registers(CPUState *cpu, int level)
4427 {   
4428     X86CPU *x86_cpu = X86_CPU(cpu);
4429     int ret;
4430         
4431     assert(cpu_is_stopped(cpu) || qemu_cpu_is_self(cpu));
4432     
4433     /*
4434      * level == KVM_PUT_FULL_STATE is only set by
4435      * kvm_cpu_synchronize_post_init() after initialization
4436      */
4437     if (kvm_tdx_enabled() && level == KVM_PUT_FULL_STATE) {
4438         tdx_post_init_vcpu(cpu);
4439     }   
4440     
4441     /* TODO: Allow accessing guest state for debug TDs. */
4442     if (kvm_tdx_enabled()) {
4443         CPUX86State *env = &x86_cpu->env;
4444         MachineState *ms = MACHINE(qdev_get_machine());
4445         TdxGuest *tdx = (TdxGuest *)object_dynamic_cast(OBJECT(ms->cgs),
4446                                                         TYPE_TDX_GUEST);
4447         /* 
4448          * Inject exception to TD guest is NOT allowed.
4449          * Now KVM has workaround to emulate
4450          * #BP injection to support GDB stub feature.
4451          */
4452         if (tdx && tdx->debug &&
4453             (env->exception_pending == 1) &&
4454             (env->exception_nr == 3))
4455             return kvm_put_vcpu_events(x86_cpu, level);
4456     
4457         return 0;
4458     }   
```

## Step4: Initializing Guest Memory
### Allocate and initialize guest memory 
The memory information required for instantiating TD VM is stored in the 
**TdxFirmware** managed by the TdxGuest struct.

**target/i386/kvm/tdx.h**
```cpp
 13 typedef struct TdxFirmwareEntry {
 14     uint32_t data_offset;
 15     uint32_t data_len;
 16     uint64_t address;
 17     uint64_t size;
 18     uint32_t type;
 19     uint32_t attributes;
 20 
 21     MemoryRegion *mr;
 22     void *mem_ptr;
 23 } TdxFirmwareEntry;
 24 
 25 typedef struct TdxFirmware {
 26     const char *file_name;
 27     uint64_t file_size;
 28 
 29     /* for split tdvf case. (TDVF_VARS.fd and TDVF_CODE.fd instead of TDVF.fd) */
 30     const char *cfv_name;
 31     uint64_t cfv_size;
 32 
 33     /* metadata */
 34     uint32_t nr_entries;
 35     TdxFirmwareEntry *entries;
 36 
 37     /* For compatiblity */
 38     bool guid_found;
 39 } TdxFirmware;
```

### KVM_TDX_INIT_MEM_REGION: add and measure guest pages.
The initialization of TDX memory region and finalization of the TD VM generation
is done by the same function **tdx_finalize_vm**. 

### KVM_TDX_FINALIAZE_VM: finalize VM and measurement
This must be after KVM_TDX_INIT_MEM_REGION.

**target/i386/kvm/tdx.c**
```cpp
 223 static void tdx_finalize_vm(Notifier *notifier, void *unused)
 224 {       
 225     Object *pm;
 226     bool ambig;
 227     MachineState *ms = MACHINE(qdev_get_machine());
 228     TdxGuest *tdx = TDX_GUEST(ms->cgs);
 229     TdxFirmwareEntry *entry;
 230 
 231     /*
 232      * object look up logic is copied from acpi_get_pm_info()
 233      * @ hw/ie86/acpi-build.c
 234      * This property override needs to be done after machine initialization
 235      * as there is no ordering of creation of objects/properties.
 236      */
 237     pm = object_resolve_path_type("", TYPE_PIIX4_PM, &ambig);
 238     if (ambig || !pm) {
 239         pm = object_resolve_path_type("", TYPE_ICH9_LPC_DEVICE, &ambig);
 240     }
 241     if (!ambig && pm) {
 242         object_property_set_uint(pm, ACPI_PM_PROP_S3_DISABLED, 1, NULL);
 243         object_property_set_uint(pm, ACPI_PM_PROP_S4_DISABLED, 1, NULL);
 244     }
 245 
 246     tdvf_hob_create(tdx, tdx_get_hob_entry(tdx));
 247 
 248     for_each_fw_entry(&tdx->fw, entry) {
 249         struct kvm_tdx_init_mem_region mem_region = {
 250             .source_addr = (__u64)entry->mem_ptr,
 251             .gpa = entry->address,
 252             .nr_pages = entry->size / 4096,
 253         };
 254 
 255         __u32 metadata = entry->attributes & TDVF_SECTION_ATTRIBUTES_EXTENDMR ?
 256                          KVM_TDX_MEASURE_MEMORY_REGION : 0;
 257 
 258         tdx_ioctl(KVM_TDX_INIT_MEM_REGION, metadata, &mem_region);
 259 
 260         qemu_ram_munmap(-1, entry->mem_ptr, entry->size);
 261         entry->mem_ptr = NULL;
 262     }
 263 
 264     tdx_ioctl(KVM_TDX_FINALIZE_VM, 0, NULL);
 265 
 266     tdx->parent_obj.ready = true;
 267 }
```

It invokes KVM_TDX_INIT_MEM_REGION per section of the TDVF binary so that TDX 
module can initialize the memory required to load the TDVF inside the TDVM. 
After initializing the TD memory region for TDVF, it invokes the
KVM_TDX_FINALIZE_VM.



## XXX
**accel/kvm/kvm-accel-ops.c**
```cpp
 27 static void *kvm_vcpu_thread_fn(void *arg)
 28 {
 29     CPUState *cpu = arg;
 ......
 40     r = kvm_init_vcpu(cpu, &error_fatal);
 41     kvm_init_cpu_signals(cpu);
 42 
 43     /* signal CPU creation */
 44     cpu_thread_signal_created(cpu);
 45     qemu_guest_random_seed_thread_part2(cpu->random_seed);
 46 
 47     do {
 48         if (cpu_can_run(cpu)) {
 49             r = kvm_cpu_exec(cpu);
 50             if (r == EXCP_DEBUG) {
 51                 cpu_handle_guest_debug(cpu);
 52             }
 53         }
 54         qemu_wait_io_event(cpu);
 55     } while (!cpu->unplug || cpu_can_run(cpu));
 56 
 57     kvm_destroy_vcpu(cpu);
 58     cpu_thread_signal_destroyed(cpu);
 59     qemu_mutex_unlock_iothread();
 60     rcu_unregister_thread();
 61     return NULL;
 62 }
 63
 64 static void kvm_start_vcpu_thread(CPUState *cpu)
 65 {
 66     char thread_name[VCPU_THREAD_NAME_SIZE];
 67 
 68     cpu->thread = g_malloc0(sizeof(QemuThread));
 69     cpu->halt_cond = g_malloc0(sizeof(QemuCond));
 70     qemu_cond_init(cpu->halt_cond);
 71     snprintf(thread_name, VCPU_THREAD_NAME_SIZE, "CPU %d/KVM",
 72              cpu->cpu_index);
 73     qemu_thread_create(cpu->thread, thread_name, kvm_vcpu_thread_fn,
 74                        cpu, QEMU_THREAD_JOINABLE);
 75 }
......
 87 static void kvm_accel_ops_class_init(ObjectClass *oc, void *data)
 88 {
 89     AccelOpsClass *ops = ACCEL_OPS_CLASS(oc);
 90 
 91     ops->create_vcpu_thread = kvm_start_vcpu_thread;
 92     ops->cpu_thread_is_idle = kvm_vcpu_thread_is_idle;
 93     ops->cpus_are_resettable = kvm_cpus_are_resettable;
 94     ops->synchronize_post_reset = kvm_cpu_synchronize_post_reset;
 95     ops->synchronize_post_init = kvm_cpu_synchronize_post_init;
 96     ops->synchronize_state = kvm_cpu_synchronize_state;
 97     ops->synchronize_pre_loadvm = kvm_cpu_synchronize_pre_loadvm;
 98 }
 99 
100 static const TypeInfo kvm_accel_ops_type = {
101     .name = ACCEL_OPS_NAME("kvm"),
102 
103     .parent = TYPE_ACCEL_OPS,
104     .class_init = kvm_accel_ops_class_init,
105     .abstract = true,
106 };
107 
108 static void kvm_accel_ops_register_types(void)
109 {
110     type_register_static(&kvm_accel_ops_type);
111 }
112 type_init(kvm_accel_ops_register_types);
```

```cpp
void qemu_init_vcpu(CPUState *cpu)
{
    MachineState *ms = MACHINE(qdev_get_machine());

    cpu->nr_cores = ms->smp.cores;
    cpu->nr_threads =  ms->smp.threads;
    cpu->stopped = true;
    cpu->random_seed = qemu_guest_random_seed_thread_part1();

    if (!cpu->as) {
        /* If the target cpu hasn't set up any address spaces itself,
         * give it the default one.
         */
        cpu->num_ases = 1;
        cpu_address_space_init(cpu, 0, "cpu-memory", cpu->memory);
    }

    /* accelerators all implement the AccelOpsClass */
    g_assert(cpus_accel != NULL && cpus_accel->create_vcpu_thread != NULL);
    cpus_accel->create_vcpu_thread(cpu);

    while (!cpu->created) {
        qemu_cond_wait(&qemu_cpu_cond, &qemu_global_mutex);
    }
}
```
