# Sending fetched instructions to decode stage
*gem5/src/cpu/o3/fetch_impl.hh*
```cpp
 961 
 962     // Pick a random thread to start trying to grab instructions from
 963     auto tid_itr = activeThreads->begin();
 964     std::advance(tid_itr, random_mt.random<uint8_t>(0, activeThreads->size() - 1));
 965 
 966     while (available_insts != 0 && insts_to_decode < decodeWidth) {
 967         ThreadID tid = *tid_itr;
 968         if (!stalls[tid].decode && !fetchQueue[tid].empty()) {
 969             const auto& inst = fetchQueue[tid].front();
 970             toDecode->insts[toDecode->size++] = inst;
 971             DPRINTF(Fetch, "[tid:%i] [sn:%llu] Sending instruction to decode "
 972                     "from fetch queue. Fetch queue size: %i.\n",
 973                     tid, inst->seqNum, fetchQueue[tid].size());
 974 
 975             wroteToTimeBuffer = true;
 976             fetchQueue[tid].pop_front();
 977             insts_to_decode++;
 978             available_insts--;
 979         }
 980 
 981         tid_itr++;
 982         // Wrap around if at end of active threads list
 983         if (tid_itr == activeThreads->end())
 984             tid_itr = activeThreads->begin();
 985     }
 986 
 987     // If there was activity this cycle, inform the CPU of it.
 988     if (wroteToTimeBuffer) {
 989         DPRINTF(Activity, "Activity this cycle.\n");
 990         cpu->activityThisCycle();
 991     }
 992 
 993     // Reset the number of the instruction we've fetched.
 994     numInst = 0;
 995 }   //end of the fetch.tick
```
The last job of the fetch stage is passing the fetched instructions
to the next stage, decode stage. 
One the above code, **toDecode** member field of the fetch 
is used as an storage located in between the fetch and decode stage. 

## FetchStruct: passing fetch stage's information to decode stage
*gem5/src/cpu/o3/fetch.hh*
```cpp
431     //Might be annoying how this name is different than the queue.
432     /** Wire used to write any information heading to decode. */
433     typename TimeBuffer<FetchStruct>::wire toDecode;
```

The toDecode is declared as a wire class defined in the TimeBuffer class. 
Also, because the TimerBuffer is a template class, 
it passes the FetchStruct that contains all fetch stage's information
required by the decode stage. Let's take a look at the FetchStruct 
to understand which information is passed to the decode stage. 

*gem5/src/cpu/o3/cpu_policy.hh*
```cpp
 60 template<class Impl>
 61 struct SimpleCPUPolicy
 62 {
 ......
 89     /** The struct for communication between fetch and decode. */
 90     typedef DefaultFetchDefaultDecode<Impl> FetchStruct;
 91 
 92     /** The struct for communication between decode and rename. */
 93     typedef DefaultDecodeDefaultRename<Impl> DecodeStruct;
 94 
 95     /** The struct for communication between rename and IEW. */
 96     typedef DefaultRenameDefaultIEW<Impl> RenameStruct;
 97 
 98     /** The struct for communication between IEW and commit. */
 99     typedef DefaultIEWDefaultCommit<Impl> IEWStruct;
100 
101     /** The struct for communication within the IEW stage. */
102     typedef ::IssueStruct<Impl> IssueStruct;
103 
104     /** The struct for all backwards communication. */
105     typedef TimeBufStruct<Impl> TimeStruct;
```

*gem5/src/cpu/o3/comm.h*
```cpp
 55 /** Struct that defines the information passed from fetch to decode. */
 56 template<class Impl>
 57 struct DefaultFetchDefaultDecode {
 58     typedef typename Impl::DynInstPtr DynInstPtr;
 59 
 60     int size;
 61 
 62     DynInstPtr insts[Impl::MaxWidth];
 63     Fault fetchFault;
 64     InstSeqNum fetchFaultSN;
 65     bool clearFetchFault;
 66 };
```
As shown in the above code, 
it passes the instructions fetched from the Icache. 
Then how this information is passed to the decode stage?
The answer is the TimeBuffer!

## TimeBuffer and wire sending the data between two stages
In actual hardware implementation, the register should be placed 
in between the two pipeline stages to share the information
processed by the previous stage to the next stage. 
For that purpose, GEM5 utilize the TimeBuffer and Wire classes. 

### TimeBuffer implementation and usage 
TimeBuffer is implemented as a template class to pass 
any information in between two different stages. 
Also, it is designed to emulate actual behavior of registers.
Therefore, at every clock tick, the TimeBuffer is advanced to contain
different content of the registers at specific clock cycle. 
For that purpose, it provides generic storage that can be utilized as a register
and interface used to access that storage containing data  captured at specific cycle. 

### Constructor and Desctructor of the TimeBuffer
```cpp
 39 template <class T>
 40 class TimeBuffer
 41 {
 42   protected:
 43     int past;
 44     int future;
 45     unsigned size;
 46     int _id;
 47 
 48     char *data;
 49     std::vector<char *> index;
 50     unsigned base;
 51 
 52     void valid(int idx) const
 53     {
 54         assert (idx >= -past && idx <= future);
 55     }
......
139   public:
140     TimeBuffer(int p, int f)
141         : past(p), future(f), size(past + future + 1),
142           data(new char[size * sizeof(T)]), index(size), base(0)
143     {   
144         assert(past >= 0 && future >= 0);
145         char *ptr = data; 
146         for (unsigned i = 0; i < size; i++) {
147             index[i] = ptr;
148             std::memset(ptr, 0, sizeof(T));
149             new (ptr) T;
150             ptr += sizeof(T);
151         }
152         
153         _id = -1;
154     }
155 
156     TimeBuffer()
157         : data(NULL)
158     {
159     }
160 
161     ~TimeBuffer()
162     {
163         for (unsigned i = 0; i < size; ++i)
164             (reinterpret_cast<T *>(index[i]))->~T();
165         delete [] data;
166     }
```
Because the TimerBuffer needs to allocate and deallocate new class object 
at every clock cycle, it's constructor is designed to utilize the 
preallocated memory called **data** member field. 
With the help of **placement new**, its constructor can initialize 
new object at specific location, index vector. 
As shown in its constructor, it populates T typed object size times 
on the data array. After that it makes the index vector point to the 
allocated objects. 
At its desctructor, it deletes the data array and every objects
pointed to by the index vector. 


### advance TimeBuffer
```cpp
 542     //Tick each of the stages
 543     fetch.tick();
 544 
 545     decode.tick();
 546 
 547     rename.tick();
 548 
 549     iew.tick();
 550 
 551     commit.tick();
 552 
 553     // Now advance the time buffers
 554     timeBuffer.advance();
 555 
 556     fetchQueue.advance();
 557     decodeQueue.advance();
 558     renameQueue.advance();
 559     iewQueue.advance();
 560 
 561     activityRec.advance();
```
The most important function of the TimeBuffer is the **advance**.
This function is invoked at every clock cycle of the processor 
to advance the TimeBuffer. Let's take a look at how the advance 
function emulates next clock tick. 

```cpp
178     void
179     advance()
180     {
181         if (++base >= size)
182             base = 0;
183 
184         int ptr = base + future;
185         if (ptr >= (int)size)
186             ptr -= size;
187         (reinterpret_cast<T *>(index[ptr]))->~T();
188         std::memset(index[ptr], 0, sizeof(T));
189         new (index[ptr]) T;
190     }
```

The base member field is initialized as zero at the construction and incremented 
at every clock cycle because the advance function is invoked at every clock cycle. 
Also, because it emulates circular storage, the base should be initialized as zero
when it exceeds size (line 181-182). 
And the future is the fixed constant passed by the configuration python script.
Therefore, after the first initialization with offset future, 
at every clock cycle, it allocates new object typed T. 
Before populating new object, it first invoke deconstructor (line 188) 
and initiate new object with the placement new (line 189). 

```cpp
192   protected:
193     //Calculate the index into this->index for element at position idx
194     //relative to now
195     inline int calculateVectorIndex(int idx) const
196     {
197         //Need more complex math here to calculate index.
198         valid(idx);
199 
200         int vector_index = idx + base;
201         if (vector_index >= (int)size) {
202             vector_index -= size;
203         } else if (vector_index < 0) {
204             vector_index += size;
205         }
206 
207         return vector_index;
208     }
209 
210   public:
211     T *access(int idx)
212     {
213         int vector_index = calculateVectorIndex(idx);
214 
215         return reinterpret_cast<T *>(index[vector_index]);
216     }
```





### Wire
```cpp
 57   public:
 58     friend class wire;
 59     class wire
 60     {
 61         friend class TimeBuffer;
 62       protected:
 63         TimeBuffer<T> *buffer;
 64         int index;
 65 
 66         void set(int idx)
 67         {   
 68             buffer->valid(idx);
 69             index = idx;
 70         }
 71 
 72         wire(TimeBuffer<T> *buf, int i)
 73             : buffer(buf), index(i)
 74         { }
 75 
 76       public:
 77         wire()
 78         { }
 79 
 80         wire(const wire &i)
 81             : buffer(i.buffer), index(i.index)
 82         { }
 83 
 84         const wire &operator=(const wire &i)
 85         {
 86             buffer = i.buffer;
 87             set(i.index);
 88             return *this;
 89         }
 90 
 91         const wire &operator=(int idx)
 92         {
 93             set(idx);
 94             return *this;
 95         }
 96 
 97         const wire &operator+=(int offset)
 98         {
 99             set(index + offset);
100             return *this;
101         }
102 
103         const wire &operator-=(int offset)
104         {
105             set(index - offset);
106             return *this;
107         }
108 
109         wire &operator++()
110         {
111             set(index + 1);
112             return *this;
113         }
114 
115         wire &operator++(int)
116         {
117             int i = index;
118             set(index + 1);
119             return wire(this, i);
120         }
121 
122         wire &operator--()
123         {
124             set(index - 1);
125             return *this;
126         }
127 
128         wire &operator--(int)
129         {
130             int i = index;
131             set(index - 1);
132             return wire(this, i);
133         }
134         T &operator*() const { return *buffer->access(index); }
135         T *operator->() const { return buffer->access(index); }
136     };
......


```
