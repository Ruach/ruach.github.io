---
layout: post
titile: "Macroop to Microops"
categories: GEM5, Microops
---
*gem5/src/sim/simulate.cc*
```cpp
 77 /** Simulate for num_cycles additional cycles.  If num_cycles is -1
 78  * (the default), do not limit simulation; some other event must
 79  * terminate the loop.  Exported to Python.
 80  * @return The SimLoopExitEvent that caused the loop to exit.
 81  */
 82 GlobalSimLoopExitEvent *
 83 simulate(Tick num_cycles)
 84 {
 85     // The first time simulate() is called from the Python code, we need to
 86     // create a thread for each of event queues referenced by the
 87     // instantiated sim objects.
 88     static bool threads_initialized = false;
 89     static std::vector<std::thread *> threads;
 90 
 91     if (!threads_initialized) {
 92         threadBarrier = new Barrier(numMainEventQueues);
 93 
 94         // the main thread (the one we're currently running on)
 95         // handles queue 0, so we only need to allocate new threads
 96         // for queues 1..N-1.  We'll call these the "subordinate" threads.
 97         for (uint32_t i = 1; i < numMainEventQueues; i++) {
 98             threads.push_back(new std::thread(thread_loop, mainEventQueue[i]));
 99         }
100 
101         threads_initialized = true;
102         simulate_limit_event =
103             new GlobalSimLoopExitEvent(mainEventQueue[0]->getCurTick(),
104                                        "simulate() limit reached", 0);
105     }
106 
107     inform("Entering event queue @ %d.  Starting simulation...\n", curTick());
108 
109     if (num_cycles < MaxTick - curTick())
110         num_cycles = curTick() + num_cycles;
111     else // counter would roll over or be set to MaxTick anyhow
112         num_cycles = MaxTick;
113 
114     simulate_limit_event->reschedule(num_cycles);
115 
116     GlobalSyncEvent *quantum_event = NULL;
117     if (numMainEventQueues > 1) {
118         if (simQuantum == 0) {
119             fatal("Quantum for multi-eventq simulation not specified");
120         }
121 
122         quantum_event = new GlobalSyncEvent(curTick() + simQuantum, simQuantum,
123                             EventBase::Progress_Event_Pri, 0);
124 
125         inParallelMode = true;
126     }
127 
128     // all subordinate (created) threads should be waiting on the
129     // barrier; the arrival of the main thread here will satisfy the
130     // barrier, and all threads will enter doSimLoop in parallel
131     threadBarrier->wait();
132     Event *local_event = doSimLoop(mainEventQueue[0]);
133     assert(local_event != NULL);
134 
135     inParallelMode = false;
136 
137     // locate the global exit event and return it to Python
138     BaseGlobalEvent *global_event = local_event->globalEvent();
139     assert(global_event != NULL);
140 
141     GlobalSimLoopExitEvent *global_exit_event =
142         dynamic_cast<GlobalSimLoopExitEvent *>(global_event);
143     assert(global_exit_event != NULL);
144 
145     //! Delete the simulation quantum event.
146     if (quantum_event != NULL) {
147         quantum_event->deschedule();
148         delete quantum_event;
149     }
150 
151     return global_exit_event;
152 }
```


*gem5/src/sim/simulate.cc*
```cpp
174 /**
175  * The main per-thread simulation loop. This loop is executed by all
176  * simulation threads (the main thread and the subordinate threads) in
177  * parallel.
178  */
179 Event *
180 doSimLoop(EventQueue *eventq)
181 {
182     // set the per thread current eventq pointer
183     curEventQueue(eventq);
184     eventq->handleAsyncInsertions();
185 
186     while (1) {
187         // there should always be at least one event (the SimLoopExitEvent
188         // we just scheduled) in the queue
189         assert(!eventq->empty());
190         assert(curTick() <= eventq->nextTick() &&
191                "event scheduled in the past");
192 
193         if (async_event && testAndClearAsyncEvent()) {
194             // Take the event queue lock in case any of the service
195             // routines want to schedule new events.
196             std::lock_guard<EventQueue> lock(*eventq);
197             if (async_statdump || async_statreset) {
198                 Stats::schedStatEvent(async_statdump, async_statreset);
199                 async_statdump = false;
200                 async_statreset = false;
201             }
202 
203             if (async_io) {
204                 async_io = false;
205                 pollQueue.service();
206             }
207 
208             if (async_exit) {
209                 async_exit = false;
210                 exitSimLoop("user interrupt received");
211             }
212 
213             if (async_exception) {
214                 async_exception = false;
215                 return NULL;
216             }
217         }
218 
219         Event *exit_event = eventq->serviceOne();
220         if (exit_event != NULL) {
221             return exit_event;
222         }
223     }
224 
225     // not reached... only exit is return on SimLoopExitEvent
226 }
```

The main execution loop of the GEM5 is the **doSimLoop**.
This loop continues until it finds the exit_event which exits the simulation.
When the program exits of unhandling fault is generated, 
GEM5 schedules the exit_event, and the doSimLoop exits the loop. 
The most important function of this loop is the **serviceOne** of the EventQueue. 

### serviceOne: process event

```cpp
203 Event *
204 EventQueue::serviceOne()
205 {
206     std::lock_guard<EventQueue> lock(*this);
207     Event *event = head;
208     Event *next = head->nextInBin;
209     event->flags.clear(Event::Scheduled);
210 
211     if (next) {
212         // update the next bin pointer since it could be stale
213         next->nextBin = head->nextBin;
214 
215         // pop the stack
216         head = next;
217     } else {
218         // this was the only element on the 'in bin' list, so get rid of
219         // the 'in bin' list and point to the next bin list
220         head = head->nextBin;
221     }
222 
223     // handle action
224     if (!event->squashed()) {
225         // forward current cycle to the time when this event occurs.
226         setCurTick(event->when());
227 
228         event->process();
229         if (event->isExitEvent()) {
230             assert(!event->flags.isSet(Event::Managed) ||
231                    !event->flags.isSet(Event::IsMainQueue)); // would be silly
232             return event;
233         }
234     } else {
235         event->flags.clear(Event::Squashed);
236     }
237 
238     event->release();
239 
240     return NULL;
241 }

```

The serviceOne function executes the emulation logic that should be done at current cycle. 
When the event is not squashed, the allocated job for that event should be executed 
by invoking the process function of the event. This job should be passed to the Event object
when the event had been scheduled. To understand underlying details, let's take a look at 
what is the Event and how the emulation process of the GEM5 generates the Event.

### Event: the basic unit of execution on GEM5 emulation
```cpp
 88 /**
 89  * Common base class for Event and GlobalEvent, so they can share flag
 90  * and priority definitions and accessor functions.  This class should
 91  * not be used directly.
 92  */
 93 class EventBase
 94 {
 95   protected:
 96     typedef unsigned short FlagsType;
 97     typedef ::Flags<FlagsType> Flags;
 98 
 99     static const FlagsType PublicRead    = 0x003f; // public readable flags
100     static const FlagsType PublicWrite   = 0x001d; // public writable flags
101     static const FlagsType Squashed      = 0x0001; // has been squashed
102     static const FlagsType Scheduled     = 0x0002; // has been scheduled
103     static const FlagsType Managed       = 0x0004; // Use life cycle manager
104     static const FlagsType AutoDelete    = Managed; // delete after dispatch
105     /**
106      * This used to be AutoSerialize. This value can't be reused
107      * without changing the checkpoint version since the flag field
108      * gets serialized.
109      */
110     static const FlagsType Reserved0     = 0x0008;
111     static const FlagsType IsExitEvent   = 0x0010; // special exit event
112     static const FlagsType IsMainQueue   = 0x0020; // on main event queue
113     static const FlagsType Initialized   = 0x7a40; // somewhat random bits
114     static const FlagsType InitMask      = 0xffc0; // mask for init bits
115 
116   public:
117     typedef int8_t Priority;
118 
119     /// Event priorities, to provide tie-breakers for events scheduled
120     /// at the same cycle.  Most events are scheduled at the default
121     /// priority; these values are used to control events that need to
122     /// be ordered within a cycle.
123 
124     /// Minimum priority
125     static const Priority Minimum_Pri =          SCHAR_MIN;
126 
127     /// If we enable tracing on a particular cycle, do that as the
128     /// very first thing so we don't miss any of the events on
129     /// that cycle (even if we enter the debugger).
130     static const Priority Debug_Enable_Pri =          -101;
131 
132     /// Breakpoints should happen before anything else (except
133     /// enabling trace output), so we don't miss any action when
134     /// debugging.
135     static const Priority Debug_Break_Pri =           -100;
137     /// CPU switches schedule the new CPU's tick event for the
138     /// same cycle (after unscheduling the old CPU's tick event).
139     /// The switch needs to come before any tick events to make
140     /// sure we don't tick both CPUs in the same cycle.
141     static const Priority CPU_Switch_Pri =             -31;
142 
143     /// For some reason "delayed" inter-cluster writebacks are
144     /// scheduled before regular writebacks (which have default
145     /// priority).  Steve?
146     static const Priority Delayed_Writeback_Pri =       -1;
147 
148     /// Default is zero for historical reasons.
149     static const Priority Default_Pri =                  0;
150 
151     /// DVFS update event leads to stats dump therefore given a lower priority
152     /// to ensure all relevant states have been updated
153     static const Priority DVFS_Update_Pri =             31;
154 
155     /// Serailization needs to occur before tick events also, so
156     /// that a serialize/unserialize is identical to an on-line
157     /// CPU switch.
158     static const Priority Serialize_Pri =               32;
159 
160     /// CPU ticks must come after other associated CPU events
161     /// (such as writebacks).
162     static const Priority CPU_Tick_Pri =                50;
163 
164     /// If we want to exit a thread in a CPU, it comes after CPU_Tick_Pri
165     static const Priority CPU_Exit_Pri =                64;
166 
167     /// Statistics events (dump, reset, etc.) come after
168     /// everything else, but before exit.
169     static const Priority Stat_Event_Pri =              90;
170 
171     /// Progress events come at the end.
172     static const Priority Progress_Event_Pri =          95;
173 
174     /// If we want to exit on this cycle, it's the very last thing
175     /// we do.
176     static const Priority Sim_Exit_Pri =               100;
177 
178     /// Maximum priority
179     static const Priority Maximum_Pri =          SCHAR_MAX;
180 };
```

The EventBase class is a root class that defines priorities among the events. 
Because GEM5 emulates entire architecture, there could be various conditions 
that specific event should be executed before the others. 
In other words, while the GEM5 emulates each tick of the entire system, 
multiple events could possibly happen at the same cycle. 
In that case, based on the event type, particular event should be processed first,
and this priority can be determined based on the priority of the Event. 

```cpp
182 /*
183  * An item on an event queue.  The action caused by a given
184  * event is specified by deriving a subclass and overriding the
185  * process() member function.
186  *
187  * Caution, the order of members is chosen to maximize data packing.
188  */
189 class Event : public EventBase, public Serializable
190 {
191     friend class EventQueue;
192 
193   private:
194     // The event queue is now a linked list of linked lists.  The
195     // 'nextBin' pointer is to find the bin, where a bin is defined as
196     // when+priority.  All events in the same bin will be stored in a
197     // second linked list (a stack) maintained by the 'nextInBin'
198     // pointer.  The list will be accessed in LIFO order.  The end
199     // result is that the insert/removal in 'nextBin' is
200     // linear/constant, and the lookup/removal in 'nextInBin' is
201     // constant/constant.  Hopefully this is a significant improvement
202     // over the current fully linear insertion.
203     Event *nextBin;
204     Event *nextInBin;
205 
206     static Event *insertBefore(Event *event, Event *curr);
207     static Event *removeItem(Event *event, Event *last);
208 
209     Tick _when;         //!< timestamp when event should be processed
210     Priority _priority; //!< event priority
211     Flags flags;
212 
213 #ifndef NDEBUG
214     /// Global counter to generate unique IDs for Event instances
215     static Counter instanceCounter;
216 
217     /// This event's unique ID.  We can also use pointer values for
218     /// this but they're not consistent across runs making debugging
219     /// more difficult.  Thus we use a global counter value when
220     /// debugging.
221     Counter instance;
222 
223     /// queue to which this event belongs (though it may or may not be
224     /// scheduled on this queue yet)
225     EventQueue *queue;
226 #endif
227 
228 #ifdef EVENTQ_DEBUG
229     Tick whenCreated;   //!< time created
230     Tick whenScheduled; //!< time scheduled
231 #endif
232 
233     void
234     setWhen(Tick when, EventQueue *q)
235     {
236         _when = when;
237 #ifndef NDEBUG
238         queue = q;
239 #endif
240 #ifdef EVENTQ_DEBUG
241         whenScheduled = curTick();
242 #endif
243     }
244 
245     bool
246     initialized() const
247     {
248         return (flags & InitMask) == Initialized;
249     }
250 
251   protected:
252     /// Accessor for flags.
253     Flags
254     getFlags() const
255     {
256         return flags & PublicRead;
257     }
258 
259     bool
260     isFlagSet(Flags _flags) const
261     {
262         assert(_flags.noneSet(~PublicRead));
263         return flags.isSet(_flags);
264     }
265 
266     /// Accessor for flags.
267     void
268     setFlags(Flags _flags)
269     {
270         assert(_flags.noneSet(~PublicWrite));
271         flags.set(_flags);
272     }
273 
274     void
275     clearFlags(Flags _flags)
276     {
277         assert(_flags.noneSet(~PublicWrite));
278         flags.clear(_flags);
279     }
280 
281     void
282     clearFlags()
283     {
284         flags.clear(PublicWrite);
285     }
286 
287     // This function isn't really useful if TRACING_ON is not defined
288     virtual void trace(const char *action);     //!< trace event activity
289 
290   protected: /* Memory management */
291     /**
292      * @{
293      * Memory management hooks for events that have the Managed flag set
294      *
295      * Events can use automatic memory management by setting the
296      * Managed flag. The default implementation automatically deletes
297      * events once they have been removed from the event queue. This
298      * typically happens when events are descheduled or have been
299      * triggered and not rescheduled.
300      *
301      * The methods below may be overridden by events that need custom
302      * memory management. For example, events exported to Python need
303      * to impement reference counting to ensure that the Python
304      * implementation of the event is kept alive while it lives in the
305      * event queue.
306      *
307      * @note Memory managers are responsible for implementing
308      * reference counting (by overriding both acquireImpl() and
309      * releaseImpl()) or checking if an event is no longer scheduled
310      * in releaseImpl() before deallocating it.
311      */
312 
313     /**
314      * Managed event scheduled and being held in the event queue.
315      */
316     void acquire()
317     {
318         if (flags.isSet(Event::Managed))
319             acquireImpl();
320     }
321 
322     /**
323      * Managed event removed from the event queue.
324      */
325     void release() {
326         if (flags.isSet(Event::Managed))
327             releaseImpl();
328     }
329 
330     virtual void acquireImpl() {}
331 
332     virtual void releaseImpl() {
333         if (!scheduled())
334             delete this;
335     }
336 
337     /** @} */
338 
339   public:
340 
341     /*
342      * Event constructor
343      * @param queue that the event gets scheduled on
344      */
345     Event(Priority p = Default_Pri, Flags f = 0)
346         : nextBin(nullptr), nextInBin(nullptr), _when(0), _priority(p),
347           flags(Initialized | f)
348     {
349         assert(f.noneSet(~PublicWrite));
350 #ifndef NDEBUG
351         instance = ++instanceCounter;
352         queue = NULL;
353 #endif
354 #ifdef EVENTQ_DEBUG
355         whenCreated = curTick();
356         whenScheduled = 0;
357 #endif
358     }
359 
360     virtual ~Event();
365     /// describing the event class.
366     virtual const char *description() const;
367 
368     /// Dump the current event data
369     void dump() const;
370 
371   public:
372     /*
373      * This member function is invoked when the event is processed
374      * (occurs).  There is no default implementation; each subclass
375      * must provide its own implementation.  The event is not
376      * automatically deleted after it is processed (to allow for
377      * statically allocated event objects).
378      *
379      * If the AutoDestroy flag is set, the object is deleted once it
380      * is processed.
381      */
382     virtual void process() = 0;
383 
384     /// Determine if the current event is scheduled
385     bool scheduled() const { return flags.isSet(Scheduled); }
386 
387     /// Squash the current event
388     void squash() { flags.set(Squashed); }
389 
390     /// Check whether the event is squashed
391     bool squashed() const { return flags.isSet(Squashed); }
392 
393     /// See if this is a SimExitEvent (without resorting to RTTI)
394     bool isExitEvent() const { return flags.isSet(IsExitEvent); }
395 
396     /// Check whether this event will auto-delete
397     bool isManaged() const { return flags.isSet(Managed); }
398     bool isAutoDelete() const { return isManaged(); }
399 
400     /// Get the time that the event is scheduled
401     Tick when() const { return _when; }
402 
403     /// Get the event priority
404     Priority priority() const { return _priority; }
405 
406     //! If this is part of a GlobalEvent, return the pointer to the
407     //! Global Event.  By default, there is no GlobalEvent, so return
408     //! NULL.  (Overridden in GlobalEvent::BarrierEvent.)
409     virtual BaseGlobalEvent *globalEvent() { return NULL; }
410 
411     void serialize(CheckpointOut &cp) const override;
412     void unserialize(CheckpointIn &cp) override;
413 };
```
As described in the comment, the Event class objects are used as an item 
on an event queue. Also, by providing specific implementation for the process
member function in a class inheriting the Event class, the execution loop 
can run the designated logic at particular cycle. 
For that purpose, it also provides member field called _when which specifies 
when the event should be executed in clock cycle. 


### EventFunctionWrapper: helper for registering callback event
There are two main usages for the Event class. First one is defining another class 
inheriting Event class and implement the process class and others.
Usually this method is used when the Event function needs to deliver some 
arguments to the logic executed by the process. 
However, when the function to be executed by the process is simple, 
it doesn't need to define another class and just pass the function using the 
predefined class EventFunctionWrapper. 

```cpp
819 class EventFunctionWrapper : public Event
820 {
821   private:
822       std::function<void(void)> callback;
823       std::string _name;
824 
825   public:
826     EventFunctionWrapper(const std::function<void(void)> &callback,
827                          const std::string &name,
828                          bool del = false,
829                          Priority p = Default_Pri)
830         : Event(p), callback(callback), _name(name)
831     {
832         if (del)
833             setFlags(AutoDelete);
834     }
835 
836     void process() { callback(); }
837 
838     const std::string
839     name() const
840     {
841         return _name + ".wrapped_function_event";
842     }
843 
844     const char *description() const { return "EventFunctionWrapped"; }
845 };
```

As shown in the above, when the function callback is passed to the constructor 
of the EventFunctionWrapper, it will be invoked later when the event is selected
by the emulation loop. Note that process function of the class just invokes the callback
passed from the constructor. Now we understand the purpose of the Event class.
However, to understand how the GEM5 manages those Events and select proper one to be executed 
at specific cycle, we need to take a look at the EventQueue. 

### EventQueue: managing all Event items

```cpp
454 /**
455  * Queue of events sorted in time order
456  *
457  * Events are scheduled (inserted into the event queue) using the
458  * schedule() method. This method either inserts a <i>synchronous</i>
459  * or <i>asynchronous</i> event.
460  *
461  * Synchronous events are scheduled using schedule() method with the
462  * argument 'global' set to false (default). This should only be done
463  * from a thread holding the event queue lock
464  * (EventQueue::service_mutex). The lock is always held when an event
465  * handler is called, it can therefore always insert events into its
466  * own event queue unless it voluntarily releases the lock.
467  *
468  * Events can be scheduled across thread (and event queue borders) by
469  * either scheduling asynchronous events or taking the target event
470  * queue's lock. However, the lock should <i>never</i> be taken
471  * directly since this is likely to cause deadlocks. Instead, code
472  * that needs to schedule events in other event queues should
473  * temporarily release its own queue and lock the new queue. This
474  * prevents deadlocks since a single thread never owns more than one
475  * event queue lock. This functionality is provided by the
476  * ScopedMigration helper class. Note that temporarily migrating
477  * between event queues can make the simulation non-deterministic, it
478  * should therefore be limited to cases where that can be tolerated
479  * (e.g., handling asynchronous IO or fast-forwarding in KVM).
480  *
481  * Asynchronous events can also be scheduled using the normal
482  * schedule() method with the 'global' parameter set to true. Unlike
483  * the previous queue migration strategy, this strategy is fully
484  * deterministic. This causes the event to be inserted in a separate
485  * queue of asynchronous events (async_queue), which is merged main
486  * event queue at the end of each simulation quantum (by calling the
487  * handleAsyncInsertions() method). Note that this implies that such
488  * events must happen at least one simulation quantum into the future,
489  * otherwise they risk being scheduled in the past by
490  * handleAsyncInsertions().
491  */
492 class EventQueue
493 {
494   private:
495     std::string objName;
496     Event *head;
497     Tick _curTick;
498 
499     //! Mutex to protect async queue.
500     std::mutex async_queue_mutex;
501 
502     //! List of events added by other threads to this event queue.
503     std::list<Event*> async_queue;
504 
505     /**
506      * Lock protecting event handling.
507      *
508      * This lock is always taken when servicing events. It is assumed
509      * that the thread scheduling new events (not asynchronous events
510      * though) have taken this lock. This is normally done by
511      * serviceOne() since new events are typically scheduled as a
512      * response to an earlier event.
513      *
514      * This lock is intended to be used to temporarily steal an event
515      * queue to support inter-thread communication when some
516      * deterministic timing can be sacrificed for speed. For example,
517      * the KVM CPU can use this support to access devices running in a
518      * different thread.
519      *
520      * @see EventQueue::ScopedMigration.
521      * @see EventQueue::ScopedRelease
522      * @see EventQueue::lock()
523      * @see EventQueue::unlock()
524      */
525     std::mutex service_mutex;
526 
527     //! Insert / remove event from the queue. Should only be called
528     //! by thread operating this queue.
529     void insert(Event *event);
530     void remove(Event *event);
531 
532     //! Function for adding events to the async queue. The added events
533     //! are added to main event queue later. Threads, other than the
534     //! owning thread, should call this function instead of insert().
535     void asyncInsert(Event *event);
536 
537     EventQueue(const EventQueue &);
538 
539   public:
540     /**
541      * Temporarily migrate execution to a different event queue.
542      *
543      * An instance of this class temporarily migrates execution to a
544      * different event queue by releasing the current queue, locking
545      * the new queue, and updating curEventQueue(). This can, for
546      * example, be useful when performing IO across thread event
547      * queues when timing is not crucial (e.g., during fast
548      * forwarding).
549      *
550      * ScopedMigration does nothing if both eqs are the same
551      */
552     class ScopedMigration
553     {
554       public:
555         ScopedMigration(EventQueue *_new_eq, bool _doMigrate = true)
556             :new_eq(*_new_eq), old_eq(*curEventQueue()),
557              doMigrate((&new_eq != &old_eq)&&_doMigrate)
558         {
559             if (doMigrate){
560                 old_eq.unlock();
561                 new_eq.lock();
562                 curEventQueue(&new_eq);
563             }
564         }
565 
566         ~ScopedMigration()
567         {
568             if (doMigrate){
569                 new_eq.unlock();
570                 old_eq.lock();
571                 curEventQueue(&old_eq);
572             }
573         }
574 
575       private:
576         EventQueue &new_eq;
577         EventQueue &old_eq;
578         bool doMigrate;
579     };
580 
581     /**
582      * Temporarily release the event queue service lock.
583      *
584      * There are cases where it is desirable to temporarily release
585      * the event queue lock to prevent deadlocks. For example, when
586      * waiting on the global barrier, we need to release the lock to
587      * prevent deadlocks from happening when another thread tries to
588      * temporarily take over the event queue waiting on the barrier.
589      */
590     class ScopedRelease
591     {
592       public:
593         ScopedRelease(EventQueue *_eq)
594             :  eq(*_eq)
595         {
596             eq.unlock();
597         }
598 
599         ~ScopedRelease()
600         {
601             eq.lock();
602         }
603 
604       private:
605         EventQueue &eq;
606     };
607 
608     EventQueue(const std::string &n);
609 
610     virtual const std::string name() const { return objName; }
611     void name(const std::string &st) { objName = st; }
612 
613     //! Schedule the given event on this queue. Safe to call from any
614     //! thread.
615     void schedule(Event *event, Tick when, bool global = false);
616 
617     //! Deschedule the specified event. Should be called only from the
618     //! owning thread.
619     void deschedule(Event *event);
620 
621     //! Reschedule the specified event. Should be called only from
622     //! the owning thread.
623     void reschedule(Event *event, Tick when, bool always = false);
624 
625     Tick nextTick() const { return head->when(); }
626     void setCurTick(Tick newVal) { _curTick = newVal; }
627     Tick getCurTick() const { return _curTick; }
628     Event *getHead() const { return head; }
629 
630     Event *serviceOne();
631 
632     // process all events up to the given timestamp.  we inline a
633     // quick test to see if there are any events to process; if so,
634     // call the internal out-of-line version to process them all.
635     void
636     serviceEvents(Tick when)
637     {
638         while (!empty()) {
639             if (nextTick() > when)
640                 break;
641 
642             /**
643              * @todo this assert is a good bug catcher.  I need to
644              * make it true again.
645              */
646             //assert(head->when() >= when && "event scheduled in the past");
647             serviceOne();
648         }
649 
650         setCurTick(when);
651     }
652 
653     // return true if no events are queued
654     bool empty() const { return head == NULL; }
655 
656     void dump() const;
657 
658     bool debugVerify() const;
659 
660     //! Function for moving events from the async_queue to the main queue.
661     void handleAsyncInsertions();
662 
663     /**
664      *  Function to signal that the event loop should be woken up because
665      *  an event has been scheduled by an agent outside the gem5 event
666      *  loop(s) whose event insertion may not have been noticed by gem5.
667      *  This function isn't needed by the usual gem5 event loop but may
668      *  be necessary in derived EventQueues which host gem5 onto other
669      *  schedulers.
670      *
671      *  @param when Time of a delayed wakeup (if known). This parameter
672      *  can be used by an implementation to schedule a wakeup in the
673      *  future if it is sure it will remain active until then.
674      *  Or it can be ignored and the event queue can be woken up now.
675      */
676     virtual void wakeup(Tick when = (Tick)-1) { }
677 
678     /**
679      *  function for replacing the head of the event queue, so that a
680      *  different set of events can run without disturbing events that have
681      *  already been scheduled. Already scheduled events can be processed
682      *  by replacing the original head back.
683      *  USING THIS FUNCTION CAN BE DANGEROUS TO THE HEALTH OF THE SIMULATOR.
684      *  NOT RECOMMENDED FOR USE.
685      */
686     Event* replaceHead(Event* s);
687 
688     /**@{*/
689     /**
690      * Provide an interface for locking/unlocking the event queue.
691      *
692      * @warn Do NOT use these methods directly unless you really know
693      * what you are doing. Incorrect use can easily lead to simulator
694      * deadlocks.
695      *
696      * @see EventQueue::ScopedMigration.
697      * @see EventQueue::ScopedRelease
698      * @see EventQueue
699      */
700     void lock() { service_mutex.lock(); }
701     void unlock() { service_mutex.unlock(); }
702     /**@}*/
703 
704     /**
705      * Reschedule an event after a checkpoint.
706      *
707      * Since events don't know which event queue they belong to,
708      * parent objects need to reschedule events themselves. This
709      * method conditionally schedules an event that has the Scheduled
710      * flag set. It should be called by parent objects after
711      * unserializing an object.
712      *
713      * @warn Only use this method after unserializing an Event.
714      */
715     void checkpointReschedule(Event *event);
716 
717     virtual ~EventQueue()
718     {
719         while (!empty())
720             deschedule(getHead());
721     }
722 };
```
EventQueue provides basic functions to manage the event queue such as 
inserting and deleting the event object from the queue. 
However, the most important method provided by the EventQueue is 
**serviceOne** function.

```cpp
203 Event *
204 EventQueue::serviceOne()
205 {
206     std::lock_guard<EventQueue> lock(*this);
207     Event *event = head;
208     Event *next = head->nextInBin;
209     event->flags.clear(Event::Scheduled);
210 
211     if (next) {
212         // update the next bin pointer since it could be stale
213         next->nextBin = head->nextBin;
214 
215         // pop the stack
216         head = next;
217     } else {
218         // this was the only element on the 'in bin' list, so get rid of
219         // the 'in bin' list and point to the next bin list
220         head = head->nextBin;
221     }
222 
223     // handle action
224     if (!event->squashed()) {
225         // forward current cycle to the time when this event occurs.
226         setCurTick(event->when());
227 
228         event->process();
229         if (event->isExitEvent()) {
230             assert(!event->flags.isSet(Event::Managed) ||
231                    !event->flags.isSet(Event::IsMainQueue)); // would be silly
232             return event;
233         }
234     } else {
235         event->flags.clear(Event::Squashed);
236     }
237 
238     event->release();
239 
240     return NULL;
241 }
```
The most important operation of the serviceOne function is invoking process function of the Event
selected from the EventQueue. As shown in the 224-233 lines, it first set the current tick 
as the tick specified the event and invokes process function of the selected Event. 

### EventQueue::schedule : insert new Event to the queue 
```cpp
 41 inline void
 42 EventQueue::schedule(Event *event, Tick when, bool global)
 43 {
 44     assert(when >= getCurTick());
 45     assert(!event->scheduled());
 46     assert(event->initialized());
 47 
 48     event->setWhen(when, this);
 49 
 50     // The check below is to make sure of two things
 51     // a. a thread schedules local events on other queues through the asyncq
 52     // b. a thread schedules global events on the asyncq, whether or not
 53     //    this event belongs to this eventq. This is required to maintain
 54     //    a total order amongst the global events. See global_event.{cc,hh}
 55     //    for more explanation.
 56     if (inParallelMode && (this != curEventQueue() || global)) {
 57         asyncInsert(event);
 58     } else {
 59         insert(event);
 60     }
 61     event->flags.set(Event::Scheduled);
 62     event->acquire();
 63 
 64     if (DTRACE(Event))
 65         event->trace("scheduled");
 66 }
```
To insert a new event to the queue, instead of utilizing the insert function 
provided by the queue directly,
schedule function should be invoked instead. 
The schedule function sets other important fields such as _when and flags of the event 
(Event::Scheduled) as a result of insertion. 
Also, it invokes insert function to actually insert the new item to the queue. 

```cpp
117 void
118 EventQueue::insert(Event *event)
119 {
120     // Deal with the head case
121     if (!head || *event <= *head) {
122         head = Event::insertBefore(event, head);
123         return;
124     }
125 
126     // Figure out either which 'in bin' list we are on, or where a new list
127     // needs to be inserted
128     Event *prev = head;
129     Event *curr = head->nextBin;
130     while (curr && *curr < *event) {
131         prev = curr;
132         curr = curr->nextBin;
133     }
134 
135     // Note: this operation may render all nextBin pointers on the
136     // prev 'in bin' list stale (except for the top one)
137     prev->nextBin = Event::insertBefore(event, curr);
138 }
```
One interesting thing to note of the insert is 
how this function inserts new item in a particular order. 
Because the EventQueue manages various events having different priorities 
scheduled at different time, the order of Events enumerated in the queue critically 
affects the functionality of the queue. 
As shown in the line 126-133, it compares curr and event Event object.
However, note that these two objects are Event object!

```cpp
415 inline bool
416 operator<(const Event &l, const Event &r)
417 {
418     return l.when() < r.when() ||
419         (l.when() == r.when() && l.priority() < r.priority());
420 }
421 
422 inline bool
423 operator>(const Event &l, const Event &r)
424 {
425     return l.when() > r.when() ||
426         (l.when() == r.when() && l.priority() > r.priority());
427 }
428 
429 inline bool
430 operator<=(const Event &l, const Event &r)
431 {
432     return l.when() < r.when() ||
433         (l.when() == r.when() && l.priority() <= r.priority());
434 }
435 inline bool
436 operator>=(const Event &l, const Event &r)
437 {
438     return l.when() > r.when() ||
439         (l.when() == r.when() && l.priority() >= r.priority());
440 }
441 
442 inline bool
443 operator==(const Event &l, const Event &r)
444 {
445     return l.when() == r.when() && l.priority() == r.priority();
446 }
447 
448 inline bool
449 operator!=(const Event &l, const Event &r)
450 {
451     return l.when() != r.when() || l.priority() != r.priority();
452 }
```
As shown in the above code, operator overriding provides a way to 
compare two different Event objects. It compares the time of two different events 
which indicate when those events should be scheduled. 
Also, it compares the priority of two events when two events are scheduled to be invoked 
at same cycle. 

### EventManager: make the SimObject as schedulable object
We can find that some GEM5 code just invokes the shcedule() function 
even though that class doesn't have the schedule as its direct member.
Therefore, we can reasonably guess that its parent class can have the schedule function.

```cpp
 567     if (!tickEvent.scheduled()) {
 568         if (_status == SwitchedOut) {
 569             DPRINTF(O3CPU, "Switched out!\n");
 570             // increment stat
 571             lastRunningCycle = curCycle();
 572         } else if (!activityRec.active() || _status == Idle) {
 573             DPRINTF(O3CPU, "Idle!\n");
 574             lastRunningCycle = curCycle();
 575             timesIdled++;
 576         } else {
 577             schedule(tickEvent, clockEdge(Cycles(1)));
 578             DPRINTF(O3CPU, "Scheduling next tick!\n");
 579         }
 580     }
```
For example, tick member function of the FullO3CPU class, invokes 
schedule function to register tickEvent. However, when we take a look at 
the class hierarchies from FullO3CPU to BaseCPU which is the base class for all CPUs,
I couldn't find the schedule function. Therefore, I checked the SimObject class 
inherited by most of the GEM5 classes. 


```cpp
class SimObject : public EventManager, public Serializable, public Drainable,
                  public Stats::Group
```
Although, I couldn't find the schedule member function in the SimObject,
I can get the clue about the schedule function from the EventManager 
inherited by the SimObject. Because schedule function register the Event 
to the EventQueue, it should be Event related with class that manages Event. 

```cpp
726 class EventManager
727 { 
728   protected:
729     /** A pointer to this object's event queue */
730     EventQueue *eventq;
731   
732   public:
733     EventManager(EventManager &em) : eventq(em.eventq) {}
734     EventManager(EventManager *em) : eventq(em->eventq) {}
735     EventManager(EventQueue *eq) : eventq(eq) {}
736     
737     EventQueue * 
738     eventQueue() const
739     {   
740         return eventq;
741     }
742     
743     void
744     schedule(Event &event, Tick when)
745     {   
746         eventq->schedule(&event, when);
747     }
748     
749     void
750     deschedule(Event &event)
751     {   
752         eventq->deschedule(&event);
753     }
754     
755     void
756     reschedule(Event &event, Tick when, bool always = false)
757     {   
758         eventq->reschedule(&event, when, always);
759     }
760     
761     void
762     schedule(Event *event, Tick when)
763     {   
764         eventq->schedule(event, when);
765     }
766     
767     void
768     deschedule(Event *event)
769     {   
770         eventq->deschedule(event);
771     }
772     
773     void
774     reschedule(Event *event, Tick when, bool always = false)
775     {   
776         eventq->reschedule(event, when, always);
777     }
778     
779     void wakeupEventQueue(Tick when = (Tick)-1)
780     {   
781         eventq->wakeup(when);
782     }
783     
784     void setCurTick(Tick newVal) { eventq->setCurTick(newVal); }
785 };
```
Yes! EventManager defines the schedule function, and it enqueues an Event object
to the EventQueue managed by the EventManager. 

