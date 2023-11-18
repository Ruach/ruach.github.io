---
layout: post
titile: "Main Simulation Loop in GEM5"
categories: [GEM5]
---

I covered how GEM5 configures the hardware parameters through the python script.
Also, in [this posting]() I explained details how python can instantiate the 
CPP classes that actually simulate hardware components. Similar to this, actual
simulation loop is implemented in CPP, but the simulation is started from the 
python script.

```python
m5.instantiate()
exit_event = m5.simulate()
```

After instantiating the platform, it invokes 'simulate' function from m5 module
to initiate simulation. Since actual simulation will be handled by the CPP, 
Let's see how this python code will transfer execution control to the CPP 
implementation.

## Overview of simulation loop
```python
def simulate(*args, **kwargs):
    global need_startup
        
    if need_startup:
        root = objects.Root.getInstance()
        for obj in root.descendants(): obj.startup()
        need_startup = False
        
        # Python exit handlers happen in reverse order.
        # We want to dump stats last.
        atexit.register(stats.dump)
    
        # register our C++ exit callback function with Python
        atexit.register(_m5.core.doExitCleanup)
    
        # Reset to put the stats in a consistent state.
        stats.reset()
        
    if _drain_manager.isDrained():
        _drain_manager.resume()
            
    # We flush stdout and stderr before and after the simulation to ensure the
    # output arrive in order.
    sys.stdout.flush()
    sys.stderr.flush()
    sim_out = _m5.event.simulate(*args, **kwargs)
    sys.stdout.flush()
    sys.stderr.flush()
```

The simulate function invokes startup function from all SimObjects instantiated
by the python script, if it needs startup. After some initialization, it invokes
CPP simulate function through '_m5.event' module. Remind that some CPP functions
related with simulation are exported to python through pybind in the very first
part of GEM5 execution. This is time to say good bye to python! From now on, 99%
of simulation code will be CPP! Be prepared to jumping into real hardware 
simulation logic!

```cpp
//gem5/src/sim/simulate.cc

GlobalSimLoopExitEvent *
simulate(Tick num_cycles)
{
    // The first time simulate() is called from the Python code, we need to
    // create a thread for each of event queues referenced by the
    // instantiated sim objects.
    static bool threads_initialized = false;
    static std::vector<std::thread *> threads;

    if (!threads_initialized) {
        threadBarrier = new Barrier(numMainEventQueues);

        // the main thread (the one we're currently running on)
        // handles queue 0, so we only need to allocate new threads
        // for queues 1..N-1.  We'll call these the "subordinate" threads.
        for (uint32_t i = 1; i < numMainEventQueues; i++) {
            threads.push_back(new std::thread(thread_loop, mainEventQueue[i]));
        }

        threads_initialized = true;
        simulate_limit_event =
            new GlobalSimLoopExitEvent(mainEventQueue[0]->getCurTick(),
                                       "simulate() limit reached", 0);
    }

    inform("Entering event queue @ %d.  Starting simulation...\n", curTick());

    if (num_cycles < MaxTick - curTick())
        num_cycles = curTick() + num_cycles;
    else // counter would roll over or be set to MaxTick anyhow
        num_cycles = MaxTick;

    simulate_limit_event->reschedule(num_cycles);

    GlobalSyncEvent *quantum_event = NULL;
    if (numMainEventQueues > 1) {
        if (simQuantum == 0) {
            fatal("Quantum for multi-eventq simulation not specified");
        }

        quantum_event = new GlobalSyncEvent(curTick() + simQuantum, simQuantum,
                            EventBase::Progress_Event_Pri, 0);

        inParallelMode = true;
    }

    // all subordinate (created) threads should be waiting on the
    // barrier; the arrival of the main thread here will satisfy the
    // barrier, and all threads will enter doSimLoop in parallel
    threadBarrier->wait();
    Event *local_event = doSimLoop(mainEventQueue[0]);
    assert(local_event != NULL);

    inParallelMode = false;

    // locate the global exit event and return it to Python
    BaseGlobalEvent *global_event = local_event->globalEvent();
    assert(global_event != NULL);

    GlobalSimLoopExitEvent *global_exit_event =
        dynamic_cast<GlobalSimLoopExitEvent *>(global_event);
    assert(global_exit_event != NULL);

    //! Delete the simulation quantum event.
    if (quantum_event != NULL) {
        quantum_event->deschedule();
        delete quantum_event;
    }

    return global_exit_event;
}
```

After going through some initialization related with threads, it invokes the 
main simulation loop 'doSimLoop'.

```cpp
//gem5/src/sim/simulate.cc

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

The central simulation sequence in GEM5 is the "doSimLoop." This loop persists
until it encounters an "exit_event" that signals the end of the simulation. In 
the event of program termination due to an unhandled fault, GEM5 schedules the 
"exit_event," prompting the "doSimLoop" to conclude. Most of the cases, it will
not face the exit_event and process events through the **serviceOne** function 
of the EventQueue.

## EventQueue: managing all Events
EventQueue manages several functions to manage generated Events, such as 
inserting and deleting the Event object from the queue. The main simulation loop
utilize this Queue to simulate hardware events. 

>EventQueue class is defined as friend class of Event class so it can access 
private and protected members of the Event objects managed by the queue. 

### serviceOne: handle scheduled event
Before deviling into the details of event, to grab the idea about how GEM5 
utilize this event for simulation, it would be helpful to go over below function.

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

The "serviceOne" function is responsible for processing events scheduled by 
simulated hardware components. Unless an event is marked as squashed, it proceeds
to execute the task associated with that event by invoking the event's 
**process** function. The process function describe the hardware logic that needs
to be simulated. 

### Other operations of EventQueue
The most important method of the EventQueue is **serviceOne** function. Because
it actually executes the hardware simulation logic. 

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

To add a new event to the queue, rather than using the queue's insert function 
directly, it is required to use the 'schedule' function. The 'schedule' function
is responsible for setting critical fields like '_when' and the event's flags 
(e.g., Event::Scheduled) during the insertion process. Additionally, it triggers
the 'insert' function to effectively place the new item into the queue.

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

An interesting aspect to observe in the 'insert' function is how it arranges the
insertion of a new item in a specific order. Given that the EventQueue manages
various events with distinct priorities scheduled at varying times, the sequence
in which Events are organized within the queue plays a vital role in emulating 
events in cycle-accurate manner. To define the order, it needs a metric to 
compare two Event objects. 

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
As depicted in the code above, operator overloading offers a mechanism for 
comparing Event objects. This comparison involves assessing the timing of two 
distinct events, indicating when these events are scheduled to occur. Additionally,
it evaluates the priority of events in cases where two events are scheduled to 
be executed during the same cycle.


## Event: the basic unit of execution on GEM5 simulation 
As a cycle-level simulator, GEM5 simulates hardware logic for each cycle. To
enable the execution of specific logic at precise points in the cycle, it should
be able to know which hardware component needs to be simulated at which cycle. 
To this end, GEM5 asks each hardware component to generate event that describes
which event should be simulated at which specific cycle. The generated events 
are managed by the EventQueue where the main simulation loop fetches the event 
from and execute simulation logic.

### Event class  
The Event class defines fundamental operations necessary for the execution of 
GEM5 events, crucial for simulating architecture. Each hardware component can 
communicate with simulation loop through the Event.

```cpp
class Event : public EventBase, public Serializable
{
    friend class EventQueue;

  private:
    // The event queue is now a linked list of linked lists.  The
    // 'nextBin' pointer is to find the bin, where a bin is defined as
    // when+priority.  All events in the same bin will be stored in a
    // second linked list (a stack) maintained by the 'nextInBin'
    // pointer.  The list will be accessed in LIFO order.  The end
    // result is that the insert/removal in 'nextBin' is
    // linear/constant, and the lookup/removal in 'nextInBin' is
    // constant/constant.  Hopefully this is a significant improvement
    // over the current fully linear insertion.
    Event *nextBin;
    Event *nextInBin;

    static Event *insertBefore(Event *event, Event *curr);
    static Event *removeItem(Event *event, Event *last);

    Tick _when;         //!< timestamp when event should be processed
    Priority _priority; //!< event priority
    Flags flags;
    .....

  public:

    /*
     * Event constructor
     * @param queue that the event gets scheduled on
     */
    Event(Priority p = Default_Pri, Flags f = 0)
        : nextBin(nullptr), nextInBin(nullptr), _when(0), _priority(p),
          flags(Initialized | f)
    {
        assert(f.noneSet(~PublicWrite));
#ifndef NDEBUG
        instance = ++instanceCounter;
        queue = NULL;
#endif
#ifdef EVENTQ_DEBUG
        whenCreated = curTick();
        whenScheduled = 0;
#endif
    }

    virtual ~Event();
    /// describing the event class.
    virtual const char *description() const;

    /// Dump the current event data
    void dump() const;

  public:
    virtual void process() = 0;

    /// Determine if the current event is scheduled
    bool scheduled() const { return flags.isSet(Scheduled); }

    /// Squash the current event
    void squash() { flags.set(Squashed); }

    /// Check whether the event is squashed
    bool squashed() const { return flags.isSet(Squashed); }

    /// See if this is a SimExitEvent (without resorting to RTTI)
    bool isExitEvent() const { return flags.isSet(IsExitEvent); }

    /// Check whether this event will auto-delete
    bool isManaged() const { return flags.isSet(Managed); }
    bool isAutoDelete() const { return isManaged(); }

    /// Get the time that the event is scheduled
    Tick when() const { return _when; }

    /// Get the event priority
    Priority priority() const { return _priority; }

    //! If this is part of a GlobalEvent, return the pointer to the
    //! Global Event.  By default, there is no GlobalEvent, so return
    //! NULL.  (Overridden in GlobalEvent::BarrierEvent.)
    virtual BaseGlobalEvent *globalEvent() { return NULL; }

    void serialize(CheckpointOut &cp) const override;
    void unserialize(CheckpointIn &cp) override;
};
```
When an event object is chosen from the queue, the main execution loop calls the
**process** member function of that class. It's important to highlight that the 
process function is declared as virtual, allowing child classes inheriting from 
the Event class to supply the necessary operations to simulate specific events. 
Additionally, the Event class has a member field named **_when**, which 
specifies the precise clock cycle at which the event should be simulated. 

```cpp
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

The EventBase class can be utilized for setting event priorities in GEM5. 
As GEM5 comprehensively simulates each system tick, multiple events can occur 
simultaneously in the same cycle. In such cases, the order of event processing 
depends on the event type and is influencedby the priority assigned to each event.

### How hardware component generates event?
I explained that through the event each hardware component can communicate with
main simulation loop, especially providing the logic and time (clock cycle) 
specifying when the simulation should be processed. Then how each hardware 
component generates the event? 
Primarily, the Event class can be employed in two distinct manners. The first 
approach is creating a new class that inherits from the Event class and 
implementing the process method. This approach is particularly valuable when the
Event function needs additional arguments to run the **process**. However, for 
simpler functions that don't mandate the creation of an additional class, GEM5
provides the pre-defined class, EventFunctionWrapper.

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
As depicted above, when a callback function is passed to the constructor of the
EventFunctionWrapper, it will be executed when the event is chosen by the 
emulation loop. It's essential to note that the process function in this class 
simply invokes the provided callback. 


### How to schedule generated event?
We've seen that the generated event can be inserted to the queue through the 
schedule function of the queue. Then it would be reasonable to think that each
CPP classes simulating hardware component should have the access to the queue 
to schedule the event. However, you won't locate a mention of the queue in the 
class; instead, you'll discover that it simply calls the schedule() function.
Embarrassingly, there is no definition for schedule function in the class! Yes 
it is inherited from another class! 

Similar to that all python classes representing hardware components are 
inherited from SimObject python class, all hardware component classes in CPP 
should be a child of SimObject

```cpp
class SimObject : public EventManager, public Serializable, public Drainable,
                  public Stats::Group
```

However, still you won't find the schedule member function in the SimObject 
class. Based on its declaration, we can understand that it inherits several 
other classses. Because schedule function register the Event to the EventQueue,
it should be Event related with class that manages Event, EventManager. 

```cpp
class EventManager
{ 
  protected:
    /** A pointer to this object's event queue */
    EventQueue *eventq;
  
  public:
    EventManager(EventManager &em) : eventq(em.eventq) {}
    EventManager(EventManager *em) : eventq(em->eventq) {}
    EventManager(EventQueue *eq) : eventq(eq) {}
    
    EventQueue * 
    eventQueue() const
    {   
        return eventq;
    }
    
    void
    schedule(Event &event, Tick when)
    {   
        eventq->schedule(&event, when);
    }
    
    void
    deschedule(Event &event)
    {   
        eventq->deschedule(&event);
    }
    
    void
    reschedule(Event &event, Tick when, bool always = false)
    {   
        eventq->reschedule(&event, when, always);
    }
    ......
    void setCurTick(Tick newVal) { eventq->setCurTick(newVal); }
};
```

Yes! EventManager defines the schedule function, and it schedules an Event object
to the EventQueue managed by the EventManager. Wait! Because it is a wrapper 
class of EventQueue to help any classes inheriting SimObject utilize the queue
(e.g., scheduling event) it should have access to the EventQueue. When you look
at the constructor of the EventManager, it needs a pointer to EventQueue! When
the pointer is passed to the constructor, it will be set as member field eventq,
and member functions of EventManager will utilize this EventQueue. 


```cpp
SimObject::SimObject(const Params *p)
    : EventManager(getEventQueue(p->eventq_index)),
      Stats::Group(nullptr),
      _params(p)
{
#ifdef DEBUG
    doDebugBreak = false;
#endif
    simObjectList.push_back(this);
    probeManager = new ProbeManager(this);
}
```

As shown in constructor of SimObject, it initializes the EventManager with 
return value from getEventQueue function, which is the EventQueue pointer.  

### Generating EventQueue
As GEM5 can have multiple mainEventQueue, EventQueue objects should be generated 
at runtime as much as it needs. The new EventQueue generation and its retrieval 
can be handled both by the 'getEventQueue' function

```cpp
EventQueue *
getEventQueue(uint32_t index)
{
    while (numMainEventQueues <= index) {
        numMainEventQueues++;
        mainEventQueue.push_back(
            new EventQueue(csprintf("MainEventQueue-%d", index)));
    }

    return mainEventQueue[index];
}
```
If existing number of mainEventQueue is smaller than the index, it generates 
new EventQueue. If not it will just return the indexed EventQueue. Okay everything
looks good except one thing. Who set the eventq_index value? You might already 
noticed that it is from Param which is used to reference automatically generated
CPP struct from the python class. Based on this, you can know that this parameter
is set by python beforehand. 


```python
class SimObject(object):
    # Specify metaclass.  Any class inheriting from SimObject will
    # get this metaclass.
    type = 'SimObject'
    abstract = True

    cxx_header = "sim/sim_object.hh"
    cxx_extra_bases = [ "Drainable", "Serializable", "Stats::Group" ]
    eventq_index = Param.UInt32(Parent.eventq_index, "Event Queue Index")

class Root(SimObject):
	.....
    # By default, root sim object and hence all other sim objects schedule
    # event on the eventq with index 0.
    eventq_index = 0
```

By default, it is set as zero and make all SimObjects utilize the first eventq
unless it is specified. 

```cpp
    Event *local_event = doSimLoop(mainEventQueue[0]);
```

Also, when you look at the invocation of doSimLoop, mainEventQueue[0] is passed 
as its paramter, which makes the simulation loop and all SimObjects presenting
hardware components can communicate through the mainEventQueue[0]. 

## Event scheduling action!
Now all CPP classes inheriting SimObject can utilize schedule function to 
schedule any events to the queue so that GEM5 simulation loop (doSimLoop) can 
fetches the event and simulate hardware logic at designated clock cycle. Let's 
take a look at the FullO3CPU class simulating O3 CPU pipeline as an example !


```cpp
template <class Impl>
class FullO3CPU : public BaseO3CPU
{ 
    ......
    EventFunctionWrapper tickEvent;
    ......
}

template <class Impl>
FullO3CPU<Impl>::FullO3CPU(DerivO3CPUParams *params)
    : BaseO3CPU(params),
      itb(params->itb),
      dtb(params->dtb),
      tickEvent([this]{ tick(); }, "FullO3CPU tick",
      ......
```

The constructor of the FullO3CPU class creates an instance of the tickEvent, 
which is an EventFunctionWrapper with lambda function calling tick function. 
This implies that when the tickEvent is scheduled and retrieved from the 
EventQueue, it will execute the tick() function. 


### Tick! Tick! Tick!
```cpp
template <class Impl>
void
FullO3CPU<Impl>::tick()
{   
    DPRINTF(O3CPU, "\n\nFullO3CPU: Ticking main, FullO3CPU.\n");
    assert(!switchedOut());
    assert(drainState() != DrainState::Drained);
    
    ++numCycles;
    updateCycleCounters(BaseCPU::CPU_STATE_ON);

    
    //Tick each of the stages
    fetch.tick();
    
    decode.tick();
    
    rename.tick();
    
    iew.tick();
    
    commit.tick();
    
    // Now advance the time buffers
    timeBuffer.advance();
    
    fetchQueue.advance();
    decodeQueue.advance();
    renameQueue.advance();
    iewQueue.advance();
    
    activityRec.advance();
    
    if (removeInstsThisCycle) {
        cleanUpRemovedInsts();
    }

    if (!tickEvent.scheduled()) {
        if (_status == SwitchedOut) {
            DPRINTF(O3CPU, "Switched out!\n");
            // increment stat
            lastRunningCycle = curCycle();
        } else if (!activityRec.active() || _status == Idle) {
            DPRINTF(O3CPU, "Idle!\n");
            lastRunningCycle = curCycle();
            timesIdled++;
        } else {
            schedule(tickEvent, clockEdge(Cycles(1)));
            DPRINTF(O3CPU, "Scheduling next tick!\n");
        }
    }

    if (!FullSystem)
        updateThreadPriority();

    tryDrain();
}
```

I will not cover the details of the tick function of O3 in this posting, but it 
simulate pipeline stage of O3 processor such as fetch, decode, rename, iew, and 
commit in the tick function. When the Event is fetched from the EventQueue 
in the serviceOne function, the Scheduled flag of the Event will be unset.
Since the tick function should be invoked at every clock cycle (to push the 
pipe line), another event should be rescheduled to be occurred at next clock 
cycle. Therefore, the tick function simulating the O3CPU will be invoked at 
every clock cycle and simulate the entire processor pipeline!


### Initial activation
To start the CPU, initial tick event should be scheduled. I will not cover the 
details here, but if you are interested in it pleas take carefully look at the 
below functions !
```cpp
template <class Impl>
void
O3ThreadContext<Impl>::activate()
{
    DPRINTF(O3CPU, "Calling activate on Thread Context %d\n",
            threadId());

    if (thread->status() == ThreadContext::Active)
        return;

    thread->lastActivate = curTick();
    thread->setStatus(ThreadContext::Active);

    // status() == Suspended
    cpu->activateContext(thread->threadId());
}
```

```cpp
template <class Impl>
void
FullO3CPU<Impl>::activateContext(ThreadID tid) 
{
    assert(!switchedOut());

    // Needs to set each stage to running as well.
    activateThread(tid);

    // We don't want to wake the CPU if it is drained. In that case,
    // we just want to flag the thread as active and schedule the tick
    // event from drainResume() instead.
    if (drainState() == DrainState::Drained)
        return;

    // If we are time 0 or if the last activation time is in the past,
    // schedule the next tick and wake up the fetch unit
    if (lastActivatedCycle == 0 || lastActivatedCycle < curTick()) {
        scheduleTickEvent(Cycles(0));
    ......
```

```cpp
template <class Impl>
class FullO3CPU : public BaseO3CPU
{ 
    ......
    void scheduleTickEvent(Cycles delay)
    {
        if (tickEvent.squashed())
            reschedule(tickEvent, clockEdge(delay));
        else if (!tickEvent.scheduled())
            schedule(tickEvent, clockEdge(delay));
    }

```
