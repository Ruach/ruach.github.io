# Basic KVM Flow
For x86 architecture, VMX is the main initialization module that provides 
initialization related functions to KVM module. Because KVM can be used by 
multiple different architectures, the proper architecture specific module should
provide corresponding functions related with initialization management such as 
hardware initialization and VM management functions.


## KVM Architecture Specific Operations
**arch/x86/kvm/vmx/main.c**
```cpp
1146 static int __init vt_init(void)
1147 {
1148         unsigned int vcpu_size = 0, vcpu_align = 0;
1149         int r;
1150 
1151         /* tdx_pre_kvm_init must be called before vmx_pre_kvm_init(). */
1152         tdx_pre_kvm_init(&vcpu_size, &vcpu_align, &vt_x86_ops.vm_size);
1153 
1154         vmx_pre_kvm_init(&vcpu_size, &vcpu_align);
1155 
1156         r = kvm_init(&vt_init_ops, vcpu_size, vcpu_align, THIS_MODULE);
1157         if (r)
1158                 goto err_vmx_post_exit;
1159 
1160         r = vmx_init();
1161         if (r)
1162                 goto err_kvm_exit;
1163 
1164         r = tdx_init();
1165         if (r)
1166                 goto err_vmx_exit;
1167 
1168         return 0;
......
1178 module_init(vt_init);
```

**vt_init** function is the VMX module initialization function. Note that it 
invokes kvm_init function with passing **vt_init_ops** structure defining all 
functions related with KVM initialization and management on x86 architecture. 


### kvm_x86_init_ops and kvm_x86_ops
```cpp
1137 static struct kvm_x86_init_ops vt_init_ops __initdata = {
1138         .cpu_has_kvm_support = vt_cpu_has_kvm_support,
1139         .disabled_by_bios = vt_disabled_by_bios,
1140         .check_processor_compatibility = vt_check_processor_compatibility,
1141         .hardware_setup = vt_hardware_setup,
1142 
1143         .runtime_ops = &vt_x86_ops,
1144 };
```

```cpp
 992 static struct kvm_x86_ops vt_x86_ops __initdata = {
 993         .hardware_unsetup = hardware_unsetup,
 994 
 995         .hardware_enable = vt_hardware_enable,
 996         .hardware_disable = vt_hardware_disable,
 997         .cpu_has_accelerated_tpr = vt_cpu_has_accelerated_tpr,
 998         .has_emulated_msr = vt_has_emulated_msr,
 999                
1000         .is_vm_type_supported = vt_is_vm_type_supported,
1001         .vm_size = sizeof(struct kvm_vmx),
1002         .vm_init = vt_vm_init,
1003         .vm_teardown = vt_vm_teardown,
1004         .vm_destroy = vt_vm_destroy,
1005 
1006         .vcpu_create = vt_vcpu_create,
1007         .vcpu_free = vt_vcpu_free,
1008         .vcpu_reset = vt_vcpu_reset,
1009 
1010         .prepare_guest_switch = vt_prepare_switch_to_guest,
1011         .vcpu_load = vt_vcpu_load,
1012         .vcpu_put = vt_vcpu_put,
......
1130         .mem_enc_op_dev = vt_mem_enc_op_dev,
1131         .mem_enc_op = vt_mem_enc_op,
1132         .mem_enc_op_vcpu = vt_mem_enc_op_vcpu,
1133 
1134         .prepare_memory_region = vt_prepare_memory_region,
1135 };
```

As shown in the above structures, VMX defines initialization functions for x86 
architecture. It is better to think the kvm is a generic code to provide 
initialization. Each architecture specific module provides related functions to
kvm module to support initialization. The most important structure is 
**kvm_x86_ops** containing all VMX initialization functions and VM management
functions

## KVM Architecture Specific Operations Initialization
**virt/kvm/kvm_main.c**
```cpp
5506 int kvm_init(void *opaque, unsigned vcpu_size, unsigned vcpu_align,
5507                   struct module *module)
5508 {
5509         struct kvm_cpu_compat_check c;
5510         int r;
5511         int cpu;
5512 
5513         r = kvm_arch_init(opaque);
5514         if (r)
5515                 goto out_fail;
5516 
5517         /*
5518          * kvm_arch_init makes sure there's at most one caller
5519          * for architectures that support multiple implementations,
5520          * like intel and amd on x86.
5521          * kvm_arch_init must be called before kvm_irqfd_init to avoid creating
5522          * conflicts in case kvm is already setup for another implementation.
5523          */
5524         r = kvm_irqfd_init();
5525         if (r)
5526                 goto out_irqfd;
5527 
5528         if (!zalloc_cpumask_var(&cpus_hardware_enabled, GFP_KERNEL)) {
5529                 r = -ENOMEM;
5530                 goto out_free_0;
5531         }
5532 
5533         r = kvm_arch_hardware_setup(opaque);
......
```

### kvm_arch_hardware_setup
**arch/x86/kvm/x86.c**
```cpp
  128 struct kvm_x86_ops kvm_x86_ops __read_mostly;
  129 EXPORT_SYMBOL_GPL(kvm_x86_ops);
......
11394 int kvm_arch_hardware_setup(void *opaque)
11395 {
11396         struct kvm_x86_init_ops *ops = opaque;
11397         int r;
11398 
11399         rdmsrl_safe(MSR_EFER, &host_efer);
11400 
11401         if (boot_cpu_has(X86_FEATURE_XSAVES)) {
11402                 rdmsrl(MSR_IA32_XSS, host_xss);
11403                 supported_xss = host_xss & KVM_SUPPORTED_XSS;
11404         }
11405 
11406         r = ops->hardware_setup();
11407         if (r != 0)
11408                 return r;
11409 
11410         memcpy(&kvm_x86_ops, ops->runtime_ops, sizeof(kvm_x86_ops));
```

The kvm_arch_hardware_setup of is invoked during the kvm_init function. Multiple implementation of this 
function exist but mapped to single architecture at compile time. Also, as x86 assigns **vt_hardware_setup** 
function pointer to **hardware_setup** member field, it will invoke vt_hardware_setup function. 

```cp
  56 static __init int vt_hardware_setup(void)
  57 {
  58         int ret;
  59 
  60         ret = hardware_setup();
  61         if (ret)
  62                 return ret;
  63 
  64 #ifdef CONFIG_INTEL_TDX_HOST
  65         if (enable_tdx && tdx_hardware_setup(&vt_x86_ops))
  66                 enable_tdx = false;
  67 
  68 #ifdef CONFIG_KVM_TDX_SEAM_BACKDOOR
  69         /*
  70          * Not a typo, direct SEAMCALL is only allowed when it won't interfere
  71          * with TDs created and managed by KVM.
  72          */
  73         if (!enable_tdx && !tdx_hardware_setup(&vt_x86_ops)) {
  74                 vt_x86_ops.do_seamcall = tdx_do_seamcall;
  75                 vt_x86_ops.do_tdenter = tdx_do_tdenter;
  76         }
  77 #endif
  78 #endif
  79 
  80         if (enable_ept) {
  81                 const u64 init_value = enable_tdx ? VMX_EPT_SUPPRESS_VE_BIT : 0ull;
  82                 kvm_mmu_set_ept_masks(enable_ept_ad_bits,
  83                                       cpu_has_vmx_ept_execute_only(), init_value);
  84                 kvm_mmu_set_spte_init_value(init_value);
  85         }
  86 
  87         return 0;
  88 }
```

In this function, tdx_hardware_setup assigns TDX specific functions to vt_x86_ops. The details 
of the function related with TDX will be explained in the following section. Note that vt_x86_ops 
variable has been initialized and pointed to by the **runtime_ops** of **kvm_x86_init_ops** struct. 

```cpp
11410         memcpy(&kvm_x86_ops, ops->runtime_ops, sizeof(kvm_x86_ops));
```

Therefore, the memcpy function invoked after returning from vt_hardware_setup copies the initialized 
list of functions specified in runtime_ops to **kvm_x86_ops**. Note that **kvm_x86_ops** variable is 
used instead of vt_x86_ops (pointed to by op->runtime_ops) all over the functions. It can be easy to 
think that vt_x86_ops are only used for initialization, and kvm_x86_ops are used after initialization 
of architecture specific operations. 


## KVM Module and IOCTL
For KVM module, which is treated as a device, it manages three different types of ioctl: 
one for KVM module itself, another for VM instances, and the other for VCPU instnaces. 

### KVM device ioctl
```cpp
5506 int kvm_init(void *opaque, unsigned vcpu_size, unsigned vcpu_align,
5507                   struct module *module)
5508 {
......
5570         kvm_chardev_ops.owner = module;
5571         kvm_vm_fops.owner = module;
5572         kvm_vcpu_fops.owner = module;
5573 
5574         r = misc_register(&kvm_dev);
5575         if (r) {
5576                 pr_err("kvm: misc device register failed\n");
5577                 goto out_unreg;
5578         }
......
```

```cpp
4703 static struct file_operations kvm_chardev_ops = {
4704         .unlocked_ioctl = kvm_dev_ioctl,
4705         .llseek         = noop_llseek,
4706         KVM_COMPAT(kvm_dev_ioctl),
4707 };
4708 
4709 static struct miscdevice kvm_dev = {
4710         KVM_MINOR,
4711         "kvm",
4712         &kvm_chardev_ops,
4713 };
```

The ioctol function **kvm_dev_ioctl** is registered as a ioctl handler of kvm 
device when the module is registered. 

### KVM VM ioctl
```cpp
4663 static long kvm_dev_ioctl(struct file *filp,
4664                           unsigned int ioctl, unsigned long arg)
4665 {
4666         long r = -EINVAL;
4667 
4668         switch (ioctl) {
4669         case KVM_GET_API_VERSION:
4670                 if (arg)
4671                         goto out;
4672                 r = KVM_API_VERSION;
4673                 break;
4674         case KVM_CREATE_VM:
4675                 r = kvm_dev_ioctl_create_vm(arg);
4676                 break;
......
4696         default:
4697                 return kvm_arch_dev_ioctl(filp, ioctl, arg);
4698         }
4699 out:
4700         return r;
4701 }
```

One of the functionalities of KVM dev ioctl is creating VM instance, which 
returns a file descriptor assigned for the generated VM instance. 

**virt/kvm/kvm_main.c**
```cpp
4614 static int kvm_dev_ioctl_create_vm(unsigned long type)
4615 {
4616         int r;
4617         struct kvm *kvm;
4618         struct file *file;
4619 
4620         kvm = kvm_create_vm(type);
4621         if (IS_ERR(kvm))
4622                 return PTR_ERR(kvm);
4623 #ifdef CONFIG_KVM_MMIO
4624         r = kvm_coalesced_mmio_init(kvm);
4625         if (r < 0)
4626                 goto put_kvm;
4627 #endif
4628         r = get_unused_fd_flags(O_CLOEXEC);
4629         if (r < 0)
4630                 goto put_kvm;
4631 
4632         snprintf(kvm->stats_id, sizeof(kvm->stats_id),
4633                         "kvm-%d", task_pid_nr(current));
4634 
4635         file = anon_inode_getfile("kvm-vm", &kvm_vm_fops, kvm, O_RDWR);
4636         if (IS_ERR(file)) {
4637                 put_unused_fd(r);
4638                 r = PTR_ERR(file);
4639                 goto put_kvm;
4640         }
......
4655         fd_install(r, file);
4656         return r;
4657 
4658 put_kvm:
4659         kvm_put_kvm(kvm);
4660         return r;
4661 }
```

During VM creation, the inode used for managing the generated VM is created and 
installed. The fd_install returns the file descriptor to the user so that user 
process can utilize the fd to manage the VM through the ioctl functions of that 
file descriptor generated by the KVM. The anon_inode_getfile function is very 
simple and does only two things: Get an inode (get the global inode variable 
anon_inode_inode, of course, you can also create a new inode through a parameter
control); Create a file structure instance and associate this inode.

```cpp
4600 
4601 static struct file_operations kvm_vm_fops = {
4602         .release        = kvm_vm_release,
4603         .unlocked_ioctl = kvm_vm_ioctl,
4604         .llseek         = noop_llseek,
4605         KVM_COMPAT(kvm_vm_compat_ioctl),
4606 };
```


### KVM VCPU ioctl
When the VM instance related ioctl is invoked, the **kvm_vm_ioctl** function 
handles the request and returns data if required. Specifically, when the 
KVM_CREATE_VCPU request is generated, KVM module generates VCPU and returns the
file descriptor bound to that VCPU instance. 

**virt/kvm/kvm_main.c**
```cpp
4340 static long kvm_vm_ioctl(struct file *filp,
4341                            unsigned int ioctl, unsigned long arg)
4342 {
4343         struct kvm *kvm = filp->private_data;
4344         void __user *argp = (void __user *)arg;
4345         int r;
4346 
4347         if (kvm->mm != current->mm || kvm->vm_bugged)
4348                 return -EIO;
4349         switch (ioctl) {
4350         case KVM_CREATE_VCPU:
......
4525         default:
4526                 r = kvm_arch_vm_ioctl(filp, ioctl, arg);
4527         }
4528 out:
4529         return r;
4530 }
```

```cpp
4340 static long kvm_vm_ioctl(struct file *filp,
4341                            unsigned int ioctl, unsigned long arg)
4342 {
......
4350         case KVM_CREATE_VCPU:
4351                 r = kvm_vm_ioctl_create_vcpu(kvm, arg);
4352                 break;
```

As similar to VM creation, the handler for VCPU is generated by the ioctl, 
**kvm_vm_ioctl**, not kvm_dev_ioctl. Note that KVM_CREATE_VCPU returns the file
descriptor for generated VCPU. 

```cpp
3552 static struct file_operations kon vm_vcpu_fops = {
3553         .release        = kvm_vcpu_release,
3554         .unlocked_ioctl = kvm_vcpu_ioctl,
3555         .mmap           = kvm_vcpu_mmap,
3556         .llseek         = noop_llseek,
3557         KVM_COMPAT(kvm_vcpu_compat_ioctl),
3558 };
3559 
3560 /*
3561  * Allocates an inode for the vcpu.
3562  */
3563 static int create_vcpu_fd(struct kvm_vcpu *vcpu)
3564 {
3565         char name[8 + 1 + ITOA_MAX_LEN + 1];
3566 
3567         snprintf(name, sizeof(name), "kvm-vcpu:%d", vcpu->vcpu_id);
3568         return anon_inode_getfd(name, &kvm_vcpu_fops, vcpu, O_RDWR | O_CLOEXEC);
3569 }
```

The anon_inode_getfd functions creates and installs a new file descriptor for a task. The 
generated VCPU file descriptor is able to handle all VCPU related operations through its 
ioctl, kvm_vcpu_ioctl.

```cpp
3739 
3740 static long kvm_vcpu_ioctl(struct file *filp,
3741                            unsigned int ioctl, unsigned long arg)
3742 {
......
3941         default:
3942                 r = kvm_arch_vcpu_ioctl(filp, ioctl, arg);
3943         }
3944 out:
3945         mutex_unlock(&vcpu->mutex);
3946         kfree(fpu);
3947         kfree(kvm_sregs);
3948         return r;
3949 }
```

### Wrap-up
For KVM, the KVM module does not manage all VM related operations but splitting 
operations into module, VM, and VCPU levels. To this end, each layer generates 
proper file descriptor and returns it to user so that user can invoke proper 
operations (running on kernel side) to manage VM instaces and VCPU belong to 
that instance. 

# KVM for TDX
**arch/x86/kvm/vmx/tdx.c** file defines functions related with TDX operations 
used by VMX. The TDX functions are provided to the VMX through the 
**kvm_x86_ops**. Also, each TDX operations can be invoked through the proper 
file descriptors generated by the KVM module. Because the TDX operations are 
Intel specific operations, they are handled by the **kvm_arch_\*_ioctl** 
\functions.

## TDX specific ioctl: KVM_MEMORY_ENCRYPT_OP
For TDX operations, **KVM_MEMORY_ENCRYPT_OP** is re-purposed to be generic ioctl
with TDX specific sub ioctl command handled by kvm_arch_\*_ioctl functions.

```cpp
 4363         case KVM_MEMORY_ENCRYPT_OP:
 4364                 r = -EINVAL;
 4365                 if (!kvm_x86_ops.mem_enc_op_dev)
 4366                         goto out;
 4367                 r = kvm_x86_ops.mem_enc_op_dev(argp);
 4368                 break;

 5533         case KVM_MEMORY_ENCRYPT_OP:
 5534                 r = -EINVAL;
 5535                 if (!kvm_x86_ops.mem_enc_op_vcpu)
 5536                         goto out;
 5537                 r = kvm_x86_ops.mem_enc_op_vcpu(vcpu, argp);
 5538                 break;

 6325         case KVM_MEMORY_ENCRYPT_OP: {
 6326                 r = -ENOTTY;
 6327                 if (kvm_x86_ops.mem_enc_op)
 6328                         r = static_call(kvm_x86_mem_enc_op)(kvm, argp);
 6329                 break;
 6330         }
```

```cpp
 992 static struct kvm_x86_ops vt_x86_ops __initdata = {
......
1130         .mem_enc_op_dev = vt_mem_enc_op_dev,
1131         .mem_enc_op = vt_mem_enc_op,
1132         .mem_enc_op_vcpu = vt_mem_enc_op_vcpu,
```

```cpp
 294 static int vt_mem_enc_op_dev(void __user *argp)
 295 {
 296         if (!enable_tdx)
 297                 return -EINVAL;
 298 
 299         return tdx_dev_ioctl(argp);
 300 }
 301 
 302 static int vt_mem_enc_op(struct kvm *kvm, void __user *argp)
 303 {
 304         if (!is_td(kvm))
 305                 return -ENOTTY;
 306 
 307         return tdx_vm_ioctl(kvm, argp);
 308 }
 309 
 310 static int vt_mem_enc_op_vcpu(struct kvm_vcpu *vcpu, void __user *argp)
 311 {
 312         if (!is_td_vcpu(vcpu))
 313                 return -EINVAL;
 314 
 315         return tdx_vcpu_ioctl(vcpu, argp);
 316 }
```

```cpp
/* Trust Domain eXtension sub-ioctl() commands. */
enum kvm_tdx_cmd_id {
        KVM_TDX_CAPABILITIES = 0,
        KVM_TDX_INIT_VM,
        KVM_TDX_INIT_VCPU,
        KVM_TDX_INIT_MEM_REGION,
        KVM_TDX_FINALIZE_VM,

        KVM_TDX_CMD_NR_MAX,
	};
```

Currently available TDX-VM operations are listed in the above code. 



