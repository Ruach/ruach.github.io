
### Interrupt makes the commit stage stop further instructions fetching
```cpp
 813 template <class Impl>
 814 void
 815 DefaultCommit<Impl>::commit()
 816 {
 817     if (FullSystem) {
 818         // Check if we have a interrupt and get read to handle it
 819         if (cpu->checkInterrupts(cpu->tcBase(0)))
 820             propagateInterrupt();
 821     }
```

```cpp
 788 template <class Impl>
 789 void
 790 DefaultCommit<Impl>::propagateInterrupt()
 791 {
 792     // Don't propagate intterupts if we are currently handling a trap or
 793     // in draining and the last observable instruction has been committed.
 794     if (commitStatus[0] == TrapPending || interrupt || trapSquash[0] ||
 795             tcSquash[0] || drainImminent)
 796         return;
 797 
 798     // Process interrupts if interrupts are enabled, not in PAL
 799     // mode, and no other traps or external squashes are currently
 800     // pending.
 801     // @todo: Allow other threads to handle interrupts.
 802 
 803     // Get any interrupt that happened
 804     interrupt = cpu->getInterrupts();
 805 
 806     // Tell fetch that there is an interrupt pending.  This
 807     // will make fetch wait until it sees a non PAL-mode PC,
 808     // at which point it stops fetching instructions.
 809     if (interrupt != NoFault)
 810         toIEW->commitInfo[0].interruptPending = true;
 811 }
```
If the commit stage found that the interrupt needs to be handled,
through the getInterrupts function,
it should first send signal to IEW stage and 
prevent further instruction fetching until the interrupt is resolved. 

### Handle interrupt at the time of instruction commit
After commit stage checks possible squash on the threads and 
presence of interrupt, 
it tries to commit the instructions.

```cpp
 976 template <class Impl>
 977 void
 978 DefaultCommit<Impl>::commitInsts()
 979 {
 980     ////////////////////////////////////
 981     // Handle commit
 982     // Note that commit will be handled prior to putting new
 983     // instructions in the ROB so that the ROB only tries to commit
 984     // instructions it has in this current cycle, and not instructions
 985     // it is writing in during this cycle.  Can't commit and squash
 986     // things at the same time...
 987     ////////////////////////////////////
 988 
 989     DPRINTF(Commit, "Trying to commit instructions in the ROB.\n");
 990 
 991     unsigned num_committed = 0;
 992 
 993     DynInstPtr head_inst;
 994 
 995     // Commit as many instructions as possible until the commit bandwidth
 996     // limit is reached, or it becomes impossible to commit any more.
 997     while (num_committed < commitWidth) {
 998         // Check for any interrupt that we've already squashed for
 999         // and start processing it.
1000         if (interrupt != NoFault)
1001             handleInterrupt();
```

If there were pending interrupt, the instructions cannot be committed. 

```cpp
 734 template <class Impl>
 735 void
 736 DefaultCommit<Impl>::handleInterrupt()
 737 {
 738     // Verify that we still have an interrupt to handle
 739     if (!cpu->checkInterrupts(cpu->tcBase(0))) {
 740         DPRINTF(Commit, "Pending interrupt is cleared by master before "
 741                 "it got handled. Restart fetching from the orig path.\n");
 742         toIEW->commitInfo[0].clearInterrupt = true;
 743         interrupt = NoFault;
 744         avoidQuiesceLiveLock = true;
 745         return;
 746     }
 747 
 748     // Wait until all in flight instructions are finished before enterring
 749     // the interrupt.
 750     if (canHandleInterrupts && cpu->instList.empty()) {
 751         // Squash or record that I need to squash this cycle if
 752         // an interrupt needed to be handled.
 753         DPRINTF(Commit, "Interrupt detected.\n");
 754 
 755         // Clear the interrupt now that it's going to be handled
 756         toIEW->commitInfo[0].clearInterrupt = true;
 757 
 758         assert(!thread[0]->noSquashFromTC);
 759         thread[0]->noSquashFromTC = true;
 760 
 761         if (cpu->checker) {
 762             cpu->checker->handlePendingInt();
 763         }
 764 
 765         // CPU will handle interrupt. Note that we ignore the local copy of
 766         // interrupt. This is because the local copy may no longer be the
 767         // interrupt that the interrupt controller thinks is being handled.
 768         cpu->processInterrupts(cpu->getInterrupts());
 769 
 770         thread[0]->noSquashFromTC = false;
 771 
 772         commitStatus[0] = TrapPending;
 773 
 774         interrupt = NoFault;
 775 
 776         // Generate trap squash event.
 777         generateTrapEvent(0, interrupt);
 778 
 779         avoidQuiesceLiveLock = false;
 780     } else {
 781         DPRINTF(Commit, "Interrupt pending: instruction is %sin "
 782                 "flight, ROB is %sempty\n",
 783                 canHandleInterrupts ? "not " : "",
 784                 cpu->instList.empty() ? "" : "not " );
 785     }
 786 }
```

### Architecture dependent interrupt checking 
```cpp
614 bool
615 X86ISA::Interrupts::checkInterrupts(ThreadContext *tc) const
616 {
617     RFLAGS rflags = tc->readMiscRegNoEffect(MISCREG_RFLAGS);
618     if (pendingUnmaskableInt) {
619         DPRINTF(LocalApic, "Reported pending unmaskable interrupt.\n");
620         return true;
621     }
622     if (rflags.intf) {
623         if (pendingExtInt) {
624             DPRINTF(LocalApic, "Reported pending external interrupt.\n");
625             return true;
626         }
627         if (IRRV > ISRV && bits(IRRV, 7, 4) >
628                bits(regs[APIC_TASK_PRIORITY], 7, 4)) {
629             DPRINTF(LocalApic, "Reported pending regular interrupt.\n");
630             return true;
631         }
632     }
633     return false;
634 }

```

### Processing interrupt through invoke
```cpp
 886 template <class Impl>
 887 void    
 888 FullO3CPU<Impl>::processInterrupts(const Fault &interrupt)
 889 {       
 890     // Check for interrupts here.  For now can copy the code that
 891     // exists within isa_fullsys_traits.hh.  Also assume that thread 0
 892     // is the one that handles the interrupts.
 893     // @todo: Possibly consolidate the interrupt checking code.
 894     // @todo: Allow other threads to handle interrupts.
 895         
 896     assert(interrupt != NoFault);
 897     this->interrupts[0]->updateIntrInfo(this->threadContexts[0]);
 898         
 899     DPRINTF(O3CPU, "Interrupt %s being handled\n", interrupt->name());
 900     this->trap(interrupt, 0, nullptr);
 901 }       
 902
 903 template <class Impl>
 904 void
 905 FullO3CPU<Impl>::trap(const Fault &fault, ThreadID tid,
 906                       const StaticInstPtr &inst)
 907 {       
 908     // Pass the thread's TC into the invoke method.
 909     fault->invoke(this->threadContexts[tid], inst);
 910 }      
```

### Generate trap event
```cpp
 526 template <class Impl>
 527 void
 528 DefaultCommit<Impl>::generateTrapEvent(ThreadID tid, Fault inst_fault)
 529 {
 530     DPRINTF(Commit, "Generating trap event for [tid:%i]\n", tid);
 531 
 532     EventFunctionWrapper *trap = new EventFunctionWrapper(
 533         [this, tid]{ processTrapEvent(tid); },
 534         "Trap", true, Event::CPU_Tick_Pri);
 535 
 536     Cycles latency = dynamic_pointer_cast<SyscallRetryFault>(inst_fault) ?
 537                      cpu->syscallRetryLatency : trapLatency;
 538 
 539     cpu->schedule(trap, cpu->clockEdge(latency));
 540     trapInFlight[tid] = true;
 541     thread[tid]->trapPending = true;
 542 }
```
