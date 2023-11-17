---
layout: post
titile: "What is the ProbePoint in the Gem5?"
categories: [GEM5, probe] 
---

*gem5/src/sim/probe/probe.hh*
```cpp
 40 /**
 41  * @file This file describes the base components used for the probe system.
 42  * There are currently 3 components:
 43  *
 44  * ProbePoint:          an event probe point i.e. send a notify from the point
 45  *                      at which an instruction was committed.
 46  *
 47  * ProbeListener:       a listener provide a notify method that is called when
 48  *                      a probe point event occurs. Multiple ProbeListeners
 49  *                      can be added to each ProbePoint.
 50  *
 51  * ProbeListenerObject: a wrapper around a SimObject that can connect to another
 52  *                      SimObject on which is will add ProbeListeners.
 53  *
 54  * ProbeManager:        used to match up ProbeListeners and ProbePoints.
 55  *                      At <b>simulation init</b> this is handled by regProbePoints
 56  *                      followed by regProbeListeners being called on each
 57  *                      SimObject in hierarchical ordering.
 58  *                      ProbeListeners can be added/removed dynamically at runtime.
 59  */
......
112 /**
113  * ProbeListener base class; here to simplify things like containers
114  * containing multiple types of ProbeListener.
115  *
116  * Note a ProbeListener is added to the ProbePoint in constructor by
117  * using the ProbeManager passed in.
118  */
119 class ProbeListener
120 {
121   public:
122     ProbeListener(ProbeManager *manager, const std::string &name);
123     virtual ~ProbeListener();
124
125   protected:
126     ProbeManager *const manager;
127     const std::string name;
128 };
129
130 /**
131  * ProbeListener base class; again used to simplify use of ProbePoints
132  * in containers and used as to define interface for adding removing
133  * listeners to the ProbePoint.
134  */
135 class ProbePoint
136 {
137   protected:
138     const std::string name;
139   public:
140     ProbePoint(ProbeManager *manager, const std::string &name);
141     virtual ~ProbePoint() {}
142
143     virtual void addListener(ProbeListener *listener) = 0;
144     virtual void removeListener(ProbeListener *listener) = 0;
145     std::string getName() const { return name; }
146 };
147
148 /**
149  * ProbeManager is a conduit class that lives on each SimObject,
150  *  and is used to match up probe listeners with probe points.
151  */
152 class ProbeManager
153 {
154   private:
155     /** Required for sensible debug messages.*/
156     const M5_CLASS_VAR_USED SimObject *object;
157     /** Vector for name look-up. */
158     std::vector<ProbePoint *> points;
159
160   public:
161     ProbeManager(SimObject *obj)
162         : object(obj)
163     {}
164     virtual ~ProbeManager() {}
165
166     /**
167      * @brief Add a ProbeListener to the ProbePoint named by pointName.
168      *        If the name doesn't resolve a ProbePoint return false.
169      * @param pointName the name of the ProbePoint to add the ProbeListener to.
170      * @param listener the ProbeListener to add.
171      * @return true if added, false otherwise.
172      */
173     bool addListener(std::string pointName, ProbeListener &listener);
174
175     /**
176      * @brief Remove a ProbeListener from the ProbePoint named by pointName.
177      *        If the name doesn't resolve a ProbePoint return false.
178      * @param pointName the name of the ProbePoint to remove the ProbeListener
179      *        from.
180      * @param listener the ProbeListener to remove.
181      * @return true if removed, false otherwise.
182      */
183     bool removeListener(std::string pointName, ProbeListener &listener);
184
185     /**
186      * @brief Add a ProbePoint to this SimObject ProbeManager.
187      * @param point the ProbePoint to add.
188      */
189     void addPoint(ProbePoint &point);
190 };

243 /**
244  * ProbePointArg generates a point for the class of Arg. As ProbePointArgs talk
245  * directly to ProbeListenerArgs of the same type, we can store the vector of
246  * ProbeListeners as their Arg type (and not as base type).
247  *
248  * Methods are provided to addListener, removeListener and notify.
249  */
250 template <typename Arg>
251 class ProbePointArg : public ProbePoint
252 {
253     /** The attached listeners. */
254     std::vector<ProbeListenerArgBase<Arg> *> listeners;
255
256   public:
257     ProbePointArg(ProbeManager *manager, std::string name)
258         : ProbePoint(manager, name)
259     {
260     }
261
262     /**
263      * @brief adds a ProbeListener to this ProbePoints notify list.
264      * @param l the ProbeListener to add to the notify list.
265      */
266     void addListener(ProbeListener *l)
267     {
268         // check listener not already added
269         if (std::find(listeners.begin(), listeners.end(), l) == listeners.end()) {
270             listeners.push_back(static_cast<ProbeListenerArgBase<Arg> *>(l));
271         }
272     }
273
274     /**
275      * @brief remove a ProbeListener from this ProbePoints notify list.
276      * @param l the ProbeListener to remove from the notify list.
277      */
278     void removeListener(ProbeListener *l)
279     {
280         listeners.erase(std::remove(listeners.begin(), listeners.end(), l),
281                         listeners.end());
282     }
283
284     /**
285      * @brief called at the ProbePoint call site, passes arg to each listener.
286      * @param arg the argument to pass to each listener.
287      */
288     void notify(const Arg &arg)
289     {
290         for (auto l = listeners.begin(); l != listeners.end(); ++l) {
291             (*l)->notify(arg);
292         }
293     }
294 };
```

ProbePointArg class provides notify method that delivers 
notification to the registered listners for a probe 
associated with this class instance.

















*gem5/src/cpu/simple/base.cc*
```cpp
572 void
573 BaseSimpleCPU::postExecute()
574 {
575     SimpleExecContext &t_info = *threadInfo[curThread];
576     SimpleThread* thread = t_info.thread;
577
578     assert(curStaticInst);
579
580     TheISA::PCState pc = threadContexts[curThread]->pcState();
581     Addr instAddr = pc.instAddr();
582     if (FullSystem && thread->profile) {
583         bool usermode = TheISA::inUserMode(threadContexts[curThread]);
584         thread->profilePC = usermode ? 1 : instAddr;
585         ProfileNode *node = thread->profile->consume(threadContexts[curThread],
586                                                      curStaticInst);
587         if (node)
588             thread->profileNode = node;
589     }
590
591     if (curStaticInst->isMemRef()) {
592         t_info.numMemRefs++;
593     }
594
595     if (curStaticInst->isLoad()) {
596         ++t_info.numLoad;
597     }
598
599     if (CPA::available()) {
600         CPA::cpa()->swAutoBegin(threadContexts[curThread], pc.nextInstAddr());
601     }
602
603     if (curStaticInst->isControl()) {
604         ++t_info.numBranches;
605     }
606
607     /* Power model statistics */
608     //integer alu accesses
609     if (curStaticInst->isInteger()){
610         t_info.numIntAluAccesses++;
611         t_info.numIntInsts++;
612     }
613
614     //float alu accesses
615     if (curStaticInst->isFloating()){
616         t_info.numFpAluAccesses++;
617         t_info.numFpInsts++;
618     }
619
620     //vector alu accesses
621     if (curStaticInst->isVector()){
622         t_info.numVecAluAccesses++;
623         t_info.numVecInsts++;
624     }
625
626     //number of function calls/returns to get window accesses
627     if (curStaticInst->isCall() || curStaticInst->isReturn()){
628         t_info.numCallsReturns++;
629     }
630
631     //the number of branch predictions that will be made
632     if (curStaticInst->isCondCtrl()){
633         t_info.numCondCtrlInsts++;
634     }
635
636     //result bus acceses
637     if (curStaticInst->isLoad()){
638         t_info.numLoadInsts++;
639     }
640
641     if (curStaticInst->isStore() || curStaticInst->isAtomic()){
642         t_info.numStoreInsts++;
643     }
644     /* End power model statistics */
645
646     t_info.statExecutedInstType[curStaticInst->opClass()]++;
647
648     if (FullSystem)
649         traceFunctions(instAddr);
650
651     if (traceData) {
652         traceData->dump();
653         delete traceData;
654         traceData = NULL;
655     }
656
657     // Call CPU instruction commit probes
658     probeInstCommit(curStaticInst, instAddr);
659 }
```

*gem5/src/cpu/simple/base.cc*
```cpp
572 void
573 BaseSimpleCPU::postExecute()
574 {
575     SimpleExecContext &t_info = *threadInfo[curThread];
576     SimpleThread* thread = t_info.thread;
577
578     assert(curStaticInst);
579
580     TheISA::PCState pc = threadContexts[curThread]->pcState();
581     Addr instAddr = pc.instAddr();
582     if (FullSystem && thread->profile) {
583         bool usermode = TheISA::inUserMode(threadContexts[curThread]);
584         thread->profilePC = usermode ? 1 : instAddr;
585         ProfileNode *node = thread->profile->consume(threadContexts[curThread],
586                                                      curStaticInst);
587         if (node)
588             thread->profileNode = node;
589     }
590
591     if (curStaticInst->isMemRef()) {
592         t_info.numMemRefs++;
593     }
594
595     if (curStaticInst->isLoad()) {
596         ++t_info.numLoad;
597     }
598
599     if (CPA::available()) {
600         CPA::cpa()->swAutoBegin(threadContexts[curThread], pc.nextInstAddr());
601     }
602
603     if (curStaticInst->isControl()) {
604         ++t_info.numBranches;
605     }
606
607     /* Power model statistics */
608     //integer alu accesses
609     if (curStaticInst->isInteger()){
610         t_info.numIntAluAccesses++;
611         t_info.numIntInsts++;
612     }
613
614     //float alu accesses
615     if (curStaticInst->isFloating()){
616         t_info.numFpAluAccesses++;
617         t_info.numFpInsts++;
618     }
619
620     //vector alu accesses
621     if (curStaticInst->isVector()){
622         t_info.numVecAluAccesses++;
623         t_info.numVecInsts++;
624     }
625
626     //number of function calls/returns to get window accesses
627     if (curStaticInst->isCall() || curStaticInst->isReturn()){
628         t_info.numCallsReturns++;
629     }
630
631     //the number of branch predictions that will be made
632     if (curStaticInst->isCondCtrl()){
633         t_info.numCondCtrlInsts++;
634     }
635
636     //result bus acceses
637     if (curStaticInst->isLoad()){
638         t_info.numLoadInsts++;
639     }
640
641     if (curStaticInst->isStore() || curStaticInst->isAtomic()){
642         t_info.numStoreInsts++;
643     }
644     /* End power model statistics */
645
646     t_info.statExecutedInstType[curStaticInst->opClass()]++;
647
648     if (FullSystem)
649         traceFunctions(instAddr);
650
651     if (traceData) {
652         traceData->dump();
653         delete traceData;
654         traceData = NULL;
655     }
656
657     // Call CPU instruction commit probes
658     probeInstCommit(curStaticInst, instAddr);
659 }
```
