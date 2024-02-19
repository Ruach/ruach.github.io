### Common Routine of VM Run and Exit
```cpp
 9731 static int vcpu_enter_guest(struct kvm_vcpu *vcpu)
 9732 {
......
 9973         for (;;) {
 9974                 exit_fastpath = static_call(kvm_x86_run)(vcpu);
 9975                 if (likely(exit_fastpath != EXIT_FASTPATH_REENTER_GUEST))
 9976                         break;
......
10078         r = static_call(kvm_x86_handle_exit)(vcpu, exit_fastpath);
10079         return r;
```

### VMEXIT handling function
```cpp
 992 static struct kvm_x86_ops vt_x86_ops __initdata = {
 ......
1044         .handle_exit = vt_handle_exit,
```

```cpp
 193 static int vt_handle_exit(struct kvm_vcpu *vcpu,
 194                              enum exit_fastpath_completion fastpath)
 195 {
 196         if (is_td_vcpu(vcpu))
 197                 return tdx_handle_exit(vcpu, fastpath);
 198 
 199         return vmx_handle_exit(vcpu, fastpath);
 200 }
```

### TDX specific handling function (If exit VPCU has run in TDX mode)
```cpp
1896 static int __tdx_handle_exit(struct kvm_vcpu *vcpu,
1897                            enum exit_fastpath_completion fastpath)
1898 {
1899         union tdx_exit_reason exit_reason = to_tdx(vcpu)->exit_reason;
1900 
1901         if (exit_reason.full == (TDX_OPERAND_BUSY | TDX_OPERAND_ID_SEPT))
1902                 return 1;
1903 
1904         if (unlikely(exit_reason.non_recoverable || exit_reason.error)) {
1905                 kvm_pr_unimpl("TD exit due to %s, Exit Reason %d\n",
1906                               tdx_seamcall_error_name(exit_reason.full),
1907                               exit_reason.basic);
1908                 if (exit_reason.basic == EXIT_REASON_TRIPLE_FAULT)
1909                         return tdx_handle_triple_fault(vcpu);
1910 
1911                 /*
1912                  * The only reason it gets EXIT_REASON_OTHER_SMI is there is
1913                  * an #MSMI in TD guest. The #MSMI is delivered right after
1914                  * SEAMCALL returns, and an #MC is delivered to host kernel
1915                  * after SMI handler returns.
1916                  *
1917                  * The #MC right after SEAMCALL is fixed up and skipped in #MC
1918                  * handler because it's an #MC happens in TD guest we cannot
1919                  * handle it with host's context.
1920                  *
1921                  * Call KVM's machine check handler explicitly here.
1922                  */
1923                 if (exit_reason.basic == EXIT_REASON_OTHER_SMI)
1924                         kvm_machine_check();
1925 
1926                 goto unhandled_exit;
1927         }
1928 
1929         WARN_ON_ONCE(fastpath != EXIT_FASTPATH_NONE);
1930 
1931         switch (exit_reason.basic) {
1932         case EXIT_REASON_EXCEPTION_NMI:
1933                 return tdx_handle_exception(vcpu);
1934         case EXIT_REASON_EXTERNAL_INTERRUPT:
1935                 return tdx_handle_external_interrupt(vcpu);
1936         case EXIT_REASON_TDCALL:
1937                 return handle_tdvmcall(vcpu);
1938         case EXIT_REASON_EPT_VIOLATION:
1939                 return tdx_handle_ept_violation(vcpu);
1940         case EXIT_REASON_EPT_MISCONFIG:
1941                 return tdx_handle_ept_misconfig(vcpu);
1942         case EXIT_REASON_DR_ACCESS:
1943                 return tdx_handle_dr(vcpu);
1944         case EXIT_REASON_TRIPLE_FAULT:
1945                 return tdx_handle_triple_fault(vcpu);
1946         case EXIT_REASON_OTHER_SMI:
1947                 /*
1948                  * Unlike VMX, all the SMI in SEAM non-root mode (i.e. when
1949                  * TD guest vcpu is running) will cause TD exit to TDX module,
1950                  * then SEAMRET to KVM. Once it exits to KVM, SMI is delivered
1951                  * and handled right away.
1952                  *
1953                  * - If it's an MSMI, it's handled above due to non_recoverable
1954                  *   bit set.
1955                  * - If it's not an MSMI, don't need to do anything here.
1956                  */
1957                 return 1;
1958         case EXIT_REASON_BUS_LOCK:
1959                 return tdx_handle_bus_lock_vmexit(vcpu);
1960         default:
1961                 break;
```


### Handling tdvmcall                                                               
```cpp                                                                             
1555 static int handle_tdvmcall(struct kvm_vcpu *vcpu)                             
1556 {                                                                             
1557         struct vcpu_tdx *tdx = to_tdx(vcpu);                                  
1558         unsigned long exit_reason;                                            
1559                                                                               
1560         if (unlikely(tdx->tdvmcall.xmm_mask))                                 
1561                 goto unsupported;                                             
1562                                                                               
1563         if (tdvmcall_exit_type(vcpu))                                         
1564                 return tdx_emulate_vmcall(vcpu);                              
1565                                                                               
1566         exit_reason = tdvmcall_exit_reason(vcpu);                             
1567                                                                               
1568         trace_kvm_tdvmcall(vcpu, exit_reason,                                 
1569                            tdvmcall_p1_read(vcpu), tdvmcall_p2_read(vcpu), 
1570                            tdvmcall_p3_read(vcpu), tdvmcall_p4_read(vcpu));
1571                                                                               
1572         switch (exit_reason) {                                                
1573         case EXIT_REASON_CPUID:                                               
1574                 return tdx_emulate_cpuid(vcpu);                               
1575         case EXIT_REASON_HLT:                                                 
1576                 return tdx_emulate_hlt(vcpu);                                 
1577         case EXIT_REASON_IO_INSTRUCTION:                                      
1578                 return tdx_emulate_io(vcpu);                                  
1579         case EXIT_REASON_MSR_READ:                                            
1580                 return tdx_emulate_rdmsr(vcpu);                               
1581         case EXIT_REASON_MSR_WRITE:                                           
1582                 return tdx_emulate_wrmsr(vcpu);                               
1583         case EXIT_REASON_EPT_VIOLATION:                                       
1584                 return tdx_emulate_mmio(vcpu);                                
1585         case TDG_VP_VMCALL_MAP_GPA:                                           
1586                 return tdx_map_gpa(vcpu);                                     
1587         case TDG_VP_VMCALL_GET_QUOTE:                                         
1588                 return tdx_get_quote(vcpu);                                   
1589         case TDG_VP_VMCALL_REPORT_FATAL_ERROR:                                
1590                 return tdx_report_fatal_error(vcpu);                          
1591         case TDG_VP_VMCALL_SETUP_EVENT_NOTIFY_INTERRUPT:                      
1592                 return tdx_setup_event_notify_interrupt(vcpu);                
1593         default:                                                              
1594                 break;                                                        
1595         }   
```

## Misc
###                                                                             
```cpp                                                                          
 233 #define BUILD_TDVMCALL_ACCESSORS(param, gpr)                                \
 234 static __always_inline                                                      \
 235 unsigned long tdvmcall_##param##_read(struct kvm_vcpu *vcpu)                \
 236 {                                                                           \
 237         return kvm_##gpr##_read(vcpu);                                      \
 238 }                                                                           \
 239 static __always_inline void tdvmcall_##param##_write(struct kvm_vcpu *vcpu, \
 240                                                      unsigned long val)     \
 241 {                                                                           \
 242         kvm_##gpr##_write(vcpu, val);                                       \
 243 }                                                                          
 244 BUILD_TDVMCALL_ACCESSORS(p1, r12);                                         
 245 BUILD_TDVMCALL_ACCESSORS(p2, r13);                                         
 246 BUILD_TDVMCALL_ACCESSORS(p3, r14);                                         
 247 BUILD_TDVMCALL_ACCESSORS(p4, r15);                                         
```                                                                             
                                      








