DEMOTE
 3657 [592226.042112]  tdx_sept_split_private_spte.cold+0x11/0x34 [kvm_intel]

 3658 [592226.042131]  tdx_handle_changed_private_spte+0x228/0x270 [kvm_intel]
 3659 [592226.042145]  __handle_changed_spte+0x748/0x790 [kvm]

 3660 [592226.042208]  __tdp_mmu_set_spte+0xb1/0x230 [kvm]
 3661 [592226.042264]  tdp_mmu_link_sp+0xf8/0x120 [kvm]
 3662 [592226.042318]  tdp_mmu_split_huge_page+0xc8/0x180 [kvm]
 3663 [592226.042372]  tdp_mmu_zap_leafs+0x3b8/0x530 [kvm]
 3664 [592226.042424]  ? bsearch+0x60/0x90
 3665 [592226.042428]  __kvm_tdp_mmu_zap_leafs+0xad/0xd0 [kvm]

 3666 [592226.042482]  __kvm_mmu_map_gfn_in_slot+0x1ce/0x3b0 [kvm]
 3667 [592226.042536]  kvm_mmu_map_gpa+0x158/0x280 [kvm]
 3668 [592226.042589]  handle_tdvmcall+0x802/0x980 [kvm_intel]
 3669 [592226.042605]  __tdx_handle_exit+0xc3/0x220 [kvm_intel]
 3670 [592226.042616]  tdx_handle_exit+0x12/0x60 [kvm_intel]
 3671 [592226.042626]  vt_handle_exit+0x26/0x30 [kvm_intel]
 3672 [592226.042637]  vcpu_enter_guest+0x7ef/0x1000 [kvm]
 3673 [592226.042683]  ? vt_vcpu_load+0x26/0x30 [kvm_intel]
 3674 [592226.042695]  ? kvm_arch_vcpu_load+0x7c/0x230 [kvm]
 3675 [592226.042739]  ? os_xsave+0x2e/0x60
 3676 [592226.042741]  vcpu_run+0x47/0x280 [kvm]


REMOVE
 3711 [592226.043075]  <TASK>
 3715 [592226.043085]  tdx_sept_drop_private_spte.cold+0x25/0x291 [kvm_intel]

 3716 [592226.043101]  ? kvm_make_all_cpus_request_except+0xe0/0x140 [kvm]
 3717 [592226.043139]  tdx_handle_changed_private_spte+0x1c7/0x270 [kvm_intel]
 3718 [592226.043154]  __handle_changed_spte+0x748/0x790 [kvm]

 3719 [592226.043215]  __tdp_mmu_set_spte+0xb1/0x230 [kvm]
 3720 [592226.043270]  tdp_mmu_zap_leafs+0x1cd/0x530 [kvm]
 3721 [592226.043326]  __kvm_tdp_mmu_zap_leafs+0xad/0xd0 [kvm]

 3722 [592226.043379]  __kvm_mmu_map_gfn_in_slot+0x1ce/0x3b0 [kvm]
 3723 [592226.043433]  kvm_mmu_map_gpa+0x158/0x280 [kvm]
 3724 [592226.043486]  handle_tdvmcall+0x802/0x980 [kvm_intel]
 3725 [592226.043500]  __tdx_handle_exit+0xc3/0x220 [kvm_intel]
 3726 [592226.043511]  tdx_handle_exit+0x12/0x60 [kvm_intel]
 3727 [592226.043522]  vt_handle_exit+0x26/0x30 [kvm_intel]
 3728 [592226.043533]  vcpu_enter_guest+0x7ef/0x1000 [kvm]
 3729 [592226.043579]  ? vt_vcpu_load+0x26/0x30 [kvm_intel]
 3730 [592226.043591]  ? kvm_arch_vcpu_load+0x7c/0x230 [kvm]
 3731 [592226.043631]  ? os_xsave+0x2e/0x60


RECLAIM (When TD destroy)
18990 [592239.976131]  show_stack+0x52/0x5c
18991 [592239.976152]  dump_stack_lvl+0x49/0x63
18992 [592239.976170]  dump_stack+0x10/0x16
18993 [592239.976184]  tdx_sept_drop_private_spte.cold+0x115/0x291 [kvm_intel]
18994 [592239.976241]  tdx_handle_changed_private_spte+0x1c7/0x270 [kvm_intel]
18995 [592239.976287]  __handle_changed_spte+0x748/0x790 [kvm]
18996 [592239.976491]  handle_removed_pt+0x14c/0x310 [kvm]
18997 [592239.976635]  __handle_changed_spte+0x3f6/0x790 [kvm]
18998 [592239.976779]  handle_removed_pt+0x14c/0x310 [kvm]
18999 [592239.976915]  __handle_changed_spte+0x3f6/0x790 [kvm]
19000 [592239.977052]  __tdp_mmu_set_spte+0xb1/0x230 [kvm]
19001 [592239.977188]  __tdp_mmu_zap_root+0x1f1/0x210 [kvm]
19002 [592239.977329]  kvm_tdp_mmu_zap_all+0x63/0xa0 [kvm]
19003 [592239.977474]  kvm_mmu_zap_all+0x64/0x80 [kvm]
19004 [592239.977620]  kvm_arch_flush_shadow_all+0x1b/0x30 [kvm]
19005 [592239.977749]  kvm_mmu_notifier_release+0x2d/0x60 [kvm]
19006 [592239.977850]  __mmu_notifier_release+0x79/0x1f0
19007 [592239.977865]  ? sysvec_apic_timer_interrupt+0x4e/0x90
19008 [592239.977877]  exit_mmap+0x191/0x1d0
19009 [592239.977889]  ? mutex_lock+0x13/0x50
19010 [592239.977895]  ? uprobe_clear_state+0xb0/0x160
19011 [592239.977903]  ? down_write+0x13/0x60
19012 [592239.977908]  mmput+0x63/0x140
19013 [592239.977918]  exit_mm+0xc7/0x120
19014 [592239.977925]  do_exit+0x247/0x6a0
19015 [592239.977929]  ? wake_up_state+0x10/0x20
19016 [592239.977938]  ? zap_other_threads+0xc0/0x120
19017 [592239.977945]  do_group_exit+0x35/0xa0
19018 [592239.977951]  __x64_sys_exit_group+0x18/0x20
19019 [592239.977956]  do_syscall_64+0x59/0x90
19020 [592239.977967]  ? do_user_addr_fault+0x1dc/0x670
19021 [592239.977979]  ? do_syscall_64+0x69/0x90
19022 [592239.977986]  ? exit_to_user_mode_prepare+0x37/0xb0
19023 [592239.977995]  ? irqentry_exit_to_user_mode+0x9/0x20
19024 [592239.978001]  ? irqentry_exit+0x3b/0x50
19025 [592239.978007]  ? exc_page_fault+0x87/0x180
19026 [592239.978012]  entry_SYSCALL_64_after_hwframe+0x63/0xcd

