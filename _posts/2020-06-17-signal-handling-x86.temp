---
layout: post
titile: "What is the frontend and how does it orchestrate different components?"
categories: risc-v, boom
---


*linux/arch/x86/kernel/traps.c*
```c
251 static void
252 do_trap(int trapnr, int signr, char *str, struct pt_regs *regs,
253   long error_code, siginfo_t *info)
254 {
255   struct task_struct *tsk = current;
256
257
258   if (!do_trap_no_signal(tsk, trapnr, str, regs, error_code))
259     return;
260   /*
261    * We want error_code and trap_nr set for userspace faults and
262    * kernelspace faults which result in die(), but not
263    * kernelspace faults which are fixed up.  die() gives the
264    * process no chance to handle the signal and notice the
265    * kernel fault information, so that won't result in polluting
266    * the information about previously queued, but not yet
267    * delivered, faults.  See also do_general_protection below.
268    */
269   tsk->thread.error_code = error_code;
270   tsk->thread.trap_nr = trapnr;
271
272   if (show_unhandled_signals && unhandled_signal(tsk, signr) &&
273       printk_ratelimit()) {
274     pr_info("%s[%d] trap %s ip:%lx sp:%lx error:%lx",
275       tsk->comm, tsk->pid, str,
276       regs->ip, regs->sp, error_code);
277     print_vma_addr(KERN_CONT " in ", regs->ip);
278     pr_cont("\n");
279   }
280
281   force_sig_info(signr, info ?: SEND_SIG_PRIV, tsk);
282 }
283 NOKPROBE_SYMBOL(do_trap);
284
285 static void do_error_trap(struct pt_regs *regs, long error_code, char *str,
286         unsigned long trapnr, int signr)
287 {
288   siginfo_t info;
289
290   RCU_LOCKDEP_WARN(!rcu_is_watching(), "entry code didn't wake RCU");
291
292   /*
293    * WARN*()s end up here; fix them up before we call the
294    * notifier chain.
295    */
296   if (!user_mode(regs) && fixup_bug(regs, trapnr))
297     return;
298
299   if (notify_die(DIE_TRAP, str, regs, error_code, trapnr, signr) !=
300       NOTIFY_STOP) {
301     cond_local_irq_enable(regs);
302     do_trap(trapnr, signr, str, regs, error_code,
303       fill_trap_info(regs, signr, trapnr, &info));
304   }
305 }
306
307 #define DO_ERROR(trapnr, signr, str, name)        \
308 dotraplinkage void do_##name(struct pt_regs *regs, long error_code) \
309 {                 \
310   do_error_trap(regs, error_code, str, trapnr, signr);    \
311 }
312
313 DO_ERROR(X86_TRAP_DE,     SIGFPE,  "divide error",    divide_error)
314 DO_ERROR(X86_TRAP_OF,     SIGSEGV, "overflow",      overflow)
315 DO_ERROR(X86_TRAP_UD,     SIGILL,  "invalid opcode",    invalid_op)
316 DO_ERROR(X86_TRAP_OLD_MF, SIGFPE,  "coprocessor segment overrun",coprocessor_segment_overrun)
317 DO_ERROR(X86_TRAP_TS,     SIGSEGV, "invalid TSS",   invalid_TSS)
318 DO_ERROR(X86_TRAP_NP,     SIGBUS,  "segment not present", segment_not_present)
319 DO_ERROR(X86_TRAP_SS,     SIGBUS,  "stack segment",   stack_segment)
320 DO_ERROR(X86_TRAP_AC,     SIGBUS,  "alignment check",   alignment_check)

*linux/kernel/signal.c*
1169 /*
1170  * Force a signal that the process can't ignore: if necessary
1171  * we unblock the signal and change any SIG_IGN to SIG_DFL.
1172  *
1173  * Note: If we unblock the signal, we always reset it to SIG_DFL,
1174  * since we do not want to have a signal handler that was blocked
1175  * be invoked when user space had explicitly blocked it.
1176  *
1177  * We don't want to have recursive SIGSEGV's etc, for example,
1178  * that is why we also clear SIGNAL_UNKILLABLE.
1179  */
1180 int
1181 force_sig_info(int sig, struct siginfo *info, struct task_struct *t)
1182 {
1183   unsigned long int flags;
1184   int ret, blocked, ignored;
1185   struct k_sigaction *action;
1186
1187   spin_lock_irqsave(&t->sighand->siglock, flags);
1188   action = &t->sighand->action[sig-1];
1189   ignored = action->sa.sa_handler == SIG_IGN;
1190   blocked = sigismember(&t->blocked, sig);
1191   if (blocked || ignored) {
1192     action->sa.sa_handler = SIG_DFL;
1193     if (blocked) {
1194       sigdelset(&t->blocked, sig);
1195       recalc_sigpending_and_wake(t);
1196     }
1197   }
1198   /*
1199    * Don't clear SIGNAL_UNKILLABLE for traced tasks, users won't expect
1200    * debugging to leave init killable.
1201    */
1202   if (action->sa.sa_handler == SIG_DFL && !t->ptrace)
1203     t->signal->flags &= ~SIGNAL_UNKILLABLE;
1204   ret = specific_send_sig_info(sig, info, t);
1205   spin_unlock_irqrestore(&t->sighand->siglock, flags);
1206
1207   return ret;
1208 }
