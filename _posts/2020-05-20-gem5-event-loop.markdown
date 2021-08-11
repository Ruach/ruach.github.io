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


```cpp
/** 
 * The main per-thread simulation loop. This loop is executed by all
 * simulation threads (the main thread and the subordinate threads) in
 * parallel.
 */ 
Event *
doSimLoop(EventQueue *eventq)
{           
    // set the per thread current eventq pointer
    curEventQueue(eventq);
    eventq->handleAsyncInsertions();

    while (1) {
        // there should always be at least one event (the SimLoopExitEvent
        // we just scheduled) in the queue
        assert(!eventq->empty());
        assert(curTick() <= eventq->nextTick() &&
               "event scheduled in the past");
        
        if (async_event && testAndClearAsyncEvent()) {
            // Take the event queue lock in case any of the service
            // routines want to schedule new events.
            std::lock_guard<EventQueue> lock(*eventq);
            if (async_statdump || async_statreset) {
                Stats::schedStatEvent(async_statdump, async_statreset);
                async_statdump = false;
                async_statreset = false;
            }
        
            if (async_io) {
                async_io = false;
                pollQueue.service();
            }
        
            if (async_exit) {
                async_exit = false;
                exitSimLoop("user interrupt received");
            }      
            
            if (async_exception) {
                async_exception = false;
                return NULL;
            }
        }
    
        Event *exit_event = eventq->serviceOne();
        if (exit_event != NULL) {
            return exit_event;
        }
    }

    // not reached... only exit is return on SimLoopExitEvent
    }   

```
