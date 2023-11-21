---
layout: post
title: "GEM5, from entry point to simulation loop"
categories: Gem5, SimObject, pybind11, metaclass
---

## Complexity of Gem5: mix of CPP and Python 
When you first take a look at the GEM5 source code, it could be confusing 
because it has **Python, CPP, and isa files** which you might haven't seen 
before. In GEM5, Most of the simulation logic is implemented as a CPP, but it 
utilizes Python heavily for platform configuration and automatic generation of
CPP class from templates. For example, ISA files define hardware logic with 
Domain Specific Language (DSL) and will be translated into CPP classes with the 
help of Python. Forget about isa file in this posting! I will go over it in 
another blog posting. 

Since the GEM5 execution is a mixture of CPP functions and Python scripts, and 
there are duplicated names for classes and functions in both files, it would be 
tricky to understand how GEM5 works. This confusion even start from the program 
execution. Let's see the gem5 execution command, particularly for simulating X86
architecture. If this is first time of using GEM5 please read some articles from
[GEM5 tutorial](https://www.gem5.org/documentation/learning_gem5/introduction/)
before reading this post.

> build/X86/gem5.opt \<Python script for configuration>
{: .prompt-info }

The gem5.opt is a **elf binary** compiled from GEM5 CPP code base. However, to 
run simulation, GEM5 requires additional configuration script written in **Python.** 
This script specifies configuration of the platform you want to simulate with 
GEM5, which includes configuration of CPU, Memory, caches and buses. Wait, I 
told you most of the simulation logic is implemented as CPP, then why suddenly
Python script is necessary for configuring simulated platform? 

I couldn't find any documents detailing the integration of Python and CPP for 
GEM5 implementation. In my opinion, the idea is to decouple hardware 
configuration from the main code base to avoid re-compilation cost. If a user
doesn't introduce new component nor want to simulate another architecture, 
adjusting the configuration of the simulated platform would not need another 
compilation. 

Irrespective of the rationale, since GEM5 extensively utilizes both Python and 
C++, the execution of code involves frequent transitions between the two 
languages. Moreover, given that the class names and attributes are either 
identical or highly similar in both Python and C++, navigating the codebase can 
be quite confusing. 

### Motivating Example
```python                                                                       
# create the system we are going to simulate                                    
system = System()                                                               
                                                                                
# Create a simple CPU                                                           
system.cpu = TimingSimpleCPU()                                                  
```                                     

When examining the Python script passed to gem5.opt, you'll notice that it calls
various functions associated with hardware components. For instance, it invokes 
the TimingSimpleCPU function.

```python 
class TimingSimpleCPU(BaseSimpleCPU):
    type = 'TimingSimpleCPU'
    cxx_header = "cpu/simple/timing.hh"

    @classmethod
    def memory_mode(cls):
        return 'timing'

    @classmethod
    def support_take_over(cls):
        return True
```

Given that it is Python code, it's evident that this function is defined in 
Python. Indeed, as evident in the provided code, it is a Python function 
instantiating a TimingSimpleCPU class object. However, somewhat confusingly, you 
can also simultaneously find the CPP implementation for TimingSimpleCPU.

```cpp
class TimingSimpleCPU : public BaseSimpleCPU
{
  public:

    TimingSimpleCPU(TimingSimpleCPUParams * params);
    virtual ~TimingSimpleCPU();

    void init() override;
```

As mentioned earlier, the CPP implementation handles the actual hardware 
simulation, while the configuration is accomplished through the Python script. 
Consequently, it is necessary to translate Python class objects into CPP class 
objects to simulate the architecture. In this posting, I will explain how this 
transformation is accomplished in GEM5.

## Allowing Python to access CPP definitions
Since Python require access to classes and attributes implemented in different 
languages, CPP, a wrapper or helper is essential. GEM5 extensively employs 
pybind11 to facilitate Python scripts in accessing CPP-defined classes 
and structs. Detailed information about pybind11 is not covered in this post, 
so it is recommended to read 
[pybind11 documentation](https://pybind11.readthedocs.io/en/stable/basics.html), 
before proceeding with further reading.

### _m5 module exporting CPP to Python
> Please be aware that our current operations involve the execution of CPP main 
> functions, not Python. The gem5.opt is an ELF binary compiled from CPP.
{: .prompt-info }

GEM5 exports required CPP implementation as the \_m5 Python module through 
pybind11. Additionally, the sub-modules are organized based on the categories 
of the C++ implementation. 



```cpp
//src/sim/main.cc

int
main(int argc, char **argv)
{
    int ret;

    // Initialize m5 special signal handling.
    initSignals();

#if PY_MAJOR_VERSION >= 3
    std::unique_ptr<wchar_t[], decltype(&PyMem_RawFree)> program(
        Py_DecodeLocale(argv[0], NULL),
        &PyMem_RawFree);
    Py_SetProgramName(program.get());
#else
    Py_SetProgramName(argv[0]);
#endif

    // Register native modules with Python's init system before
    // initializing the interpreter.
    registerNativeModules();

    // initialize embedded Python interpreter
    Py_Initialize();

    // Initialize the embedded m5 Python library
    ret = EmbeddedPython::initAll();

    if (ret == 0) {
        // start m5
        ret = m5Main(argc, argv);
    }

    // clean up Python intepreter.
    Py_Finalize();

    return ret;
    }

```

GEM5 defines EmbeddedPython class in CPP to provide all functions and attributes 
for developer to export through the pybind11. The **EmbeddedPython::initAll** 
function exposes the required C++ definitions for running the simulation. Upon 
export, it then executes the m5Main function, transferring control from the CPP 
to Python. 

```cpp
// src/sim/init.cc

EmbeddedPyBind::initAll()
{
    std::list<EmbeddedPyBind *> pending;

    py::module m_m5 = py::module("_m5");
    m_m5.attr("__package__") = py::cast("_m5");

    pybind_init_core(m_m5);
    pybind_init_debug(m_m5);

    pybind_init_event(m_m5);
    pybind_init_stats(m_m5);

    for (auto &kv : getMap()) {
        auto &obj = kv.second;
        if (obj->base.empty()) {
            obj->init(m_m5);
        } else {
            pending.push_back(obj);
        }
    }

    while (!pending.empty()) {
        for (auto it = pending.begin(); it != pending.end(); ) {
            EmbeddedPyBind &obj = **it;
            if (obj.depsReady()) {
                obj.init(m_m5);
                it = pending.erase(it);
            } else {
                ++it;
            }
        }
    }

#if PY_MAJOR_VERSION >= 3
    return m_m5.ptr();
#endif
}
```

The Python-exported CPP implementations from the initAll module can be categorized 
into two groups. The initial category comprises CPP functions associated with 
general operations essential for simulation, including debugging, simulation loops,
and statistical operations. The second category involves exporting a parameter 
struct designed for instantiating hardware components responsible for simulating 
the architecture. 



#### Pybind initialization for simulation
Functions named  "pybind_init_XXX" exports CPP implementations required for the
simulation. It exports CPP classes and functions relevant to specific categories 
as sub modules such as core, debug, event, and stats. 


```cpp
pybind_init_event(py::module &m_native)
{
    py::module m = m_native.def_submodule("event");

    m.def("simulate", &simulate,
          py::arg("ticks") = MaxTick);
    m.def("exitSimLoop", &exitSimLoop);
    m.def("getEventQueue", []() { return curEventQueue(); },
          py::return_value_policy::reference);
    m.def("setEventQueue", [](EventQueue *q) { return curEventQueue(q); });
    m.def("getEventQueue", &getEventQueue,
          py::return_value_policy::reference);

    py::class_<EventQueue>(m, "EventQueue")
        .def("name",  [](EventQueue *eq) { return eq->name(); })
        .def("dump", &EventQueue::dump)
        .def("schedule", [](EventQueue *eq, PyEvent *e, Tick t) {
                eq->schedule(e, t);
            }, py::arg("event"), py::arg("when"))
        .def("deschedule", &EventQueue::deschedule,
             py::arg("event"))
        .def("reschedule", &EventQueue::reschedule,
             py::arg("event"), py::arg("tick"), py::arg("always") = false)
        ;
```

For example, Python function should be able to invoke CPP functions associated 
with hardware simulation because actual simulation is done by CPP not python. 
As depicted in the example, it exports simulation-related functions under 
sub-modules '_m5.event'. Later, the exported simulate function will be invoked
from python to start hardware simulation. 


#### Pybind Initialization for HW components
In contrast to functions in the first category, which are already implemented in
the CPP code base of GEM5, certain CPP implementations are automatically generated
during compile time. Consequently, exporting them is not feasible in the same 
manner as the first category, as the module name is unknown prior to generation. 
Additionally, if users incorporate extra hardware components, they must be added 
to the CPP class for proper exportation through Pybind. I will explain details 
about what CPP implementations will be automatically generated soon, so please 
bear with me.

```cpp
std::map<std::string, EmbeddedPyBind *> &
EmbeddedPyBind::getMap()
{   
    static std::map<std::string, EmbeddedPyBind *> objs;
    return objs;
}

void
EmbeddedPyBind::init(py::module &m)
{
    if (!registered) {
        initFunc(m);
        registered = true;
    } else {
        cprintf("Warning: %s already registered.\n", name);
    }
}
```

EmbeddedPyBind class defines map 'objs' to manage all EmbeddedPyBind objects and
return this map when the getMap function is invoked.  The initAll function
iterates this objects returned from getMap function and invokes 'init' function 
of the EmbeddedPyBind object. It further invokes initFunc which is a private 
function pointer member field of EmbeddedPyBind class. 


```cpp
EmbeddedPyBind::EmbeddedPyBind(const char *_name,
                               void (*init_func)(py::module &),
                               const char *_base)
    : initFunc(init_func), registered(false), name(_name), base(_base)
{
    getMap()[_name] = this;
}

EmbeddedPyBind::EmbeddedPyBind(const char *_name,
                               void (*init_func)(py::module &))
    : initFunc(init_func), registered(false), name(_name), base("")
{
    getMap()[_name] = this;
}
```

This function pointer is initialized by constructor of the EmbeddedPyBind class. 
However, you will not be able to find any relevant code instantiating 
EmbeddedPyBind for system component class. The reason is GEM5 automatically 
generate CPP code snippet, and EmbeddedPyBind class will be instantiated by that 
code. I will cover the details soon! Let's assume that all required CPP 
implementations were exported to Python through pybind11. 


## Transferring execution control to Python
After exporting CPP implementation, now it can finally jumps to GEM5 Python 
code base. Note that it will not execute the script initially passed to the 
gem5.opt executable. 

```cpp
//src/sim/init.cc

const char * __attribute__((weak)) m5MainCommands[] = {
    "import m5",
    "m5.main()",
    0 // sentinel is required
};

int m5Main(int argc, char **_argv)
{
#if HAVE_PROTOBUF
    // Verify that the version of the protobuf library that we linked
    // against is compatible with the version of the headers we
    // compiled against.
    GOOGLE_PROTOBUF_VERIFY_VERSION;
#endif
    
        
#if PY_MAJOR_VERSION >= 3
    typedef std::unique_ptr<wchar_t[], decltype(&PyMem_RawFree)> WArgUPtr;
    std::vector<WArgUPtr> v_argv;
    std::vector<wchar_t *> vp_argv;
    v_argv.reserve(argc);
    vp_argv.reserve(argc);
    for (int i = 0; i < argc; i++) {
        v_argv.emplace_back(Py_DecodeLocale(_argv[i], NULL), &PyMem_RawFree);
        vp_argv.emplace_back(v_argv.back().get());
    }
    
    wchar_t **argv = vp_argv.data();
#else
    char **argv = _argv;
#endif

    PySys_SetArgv(argc, argv);
        
    // We have to set things up in the special __main__ module
    PyObject *module = PyImport_AddModule(PyCC("__main__"));
    if (module == NULL)
        panic("Could not import __main__");
    PyObject *dict = PyModule_GetDict(module);

    // import the main m5 module
    PyObject *result;
    const char **command = m5MainCommands;

    // evaluate each command in the m5MainCommands array (basically a
    // bunch of Python statements.
    while (*command) {
        result = PyRun_String(*command, Py_file_input, dict, dict);
        if (!result) {
            PyErr_Print();
            return 1;
        }
        Py_DECREF(result);

        command++;
    }

#if HAVE_PROTOBUF
    google::protobuf::ShutdownProtobufLibrary();
#endif

    return 0;
}
```
To transfer execution control to Python code, it invokes 
[PyRun_String](https://docs.Python.org/3/c-api/veryhigh.html).
PyRun_String is a function in the Python C API that allows you to execute a 
Python code snippet from a C program. It takes a string containing the Python 
code as one of its arguments and executes it within the Python interpreter.
As depicted in the above CPP string, m5MainCommands, it will invoks m5.main 
through PyRun_String. 

### GEM5 m5 main Python code
> From this part, the execution is transferred to Python.
{: .prompt-info }

```python
//src/Python/m5/main.py 

def main(*args):
    import m5
    
    from . import core
    from . import debug
    from . import defines
    from . import event
    from . import info
    from . import stats
    from . import trace
    
    from .util import inform, fatal, panic, isInteractive
    from m5.util.terminal_formatter import TerminalFormatter
    
    if len(args) == 0:
        options, arguments = parse_options()
    elif len(args) == 2:
        options, arguments = args
    else:
        raise TypeError("main() takes 0 or 2 arguments (%d given)" % len(args))
    
    m5.options = options
    
    # Set the main event queue for the main thread.
    event.mainq = event.getEventQueue(0)
    event.setEventQueue(event.mainq)
    ......
    sys.argv = arguments
    sys.path = [ os.path.dirname(sys.argv[0]) ] + sys.path

    filename = sys.argv[0]
    filedata = open(filename, 'r').read()
    filecode = compile(filedata, filename, 'exec')
    scope = { '__file__' : filename,
              '__name__' : '__m5_main__' }
    if options.pdb:
        import pdb
        import traceback

        pdb = pdb.Pdb()
        try:
            pdb.run(filecode, scope)
        except SystemExit:
            print("The program exited via sys.exit(). Exit status: ", end=' ')
            print(sys.exc_info()[1])
        except:
            traceback.print_exc()
            print("Uncaught exception. Entering post mortem debugging")
            t = sys.exc_info()[2]
            while t.tb_next is not None:
                t = t.tb_next
                pdb.interaction(t.tb_frame,t)
    else:
        exec(filecode, scope)
```

There are two important initialization code in the above Python code: 
initializing main event queue and execute Python snippet originally provided 
to gem5.opt. The event queue will be covered in [another blog posting]().
You might remember that we have passed config script defining configuration 
of one platform we want to simulate. That Python script is passed to above 
Python code snippet through 'sys.argv[0]', and compiled and exec. 
Therefore, it will not return to CPP, but the execution control is transferred
to configuration Python script!


## Python configuration to CPP implementation! 
To understand how Python configuration script interacts with CPP implementation 
in simulating one architecture, I will pick very simple configuration script 
provided by GEM5.

```python
# create the system we are going to simulate 
system = System() 

# Create a simple CPU
system.cpu = TimingSimpleCPU()

# Create a memory bus, a system crossbar, in this case
system.membus = SystemXBar()

# Hook the CPU ports up to the membus
system.cpu.icache_port = system.membus.slave
system.cpu.dcache_port = system.membus.slave

# Create a DDR3 memory controller and connect it to the membus
system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.master
```

In the Python configuration script above, it creates instances of the CPU, 
crossbar, and DRAM. Additionally, it establishes the connection between the CPU 
and memory via the crossbar. As previously explained, GEM5 represents each 
hardware component as a CPP class for simulation. Consequently, the 
configurations defined in Python for the simulated platform need to be translated
into CPP implementation to effectively simulate hardware logic. This involves 
transforming the hardware components and the interconnections between them.


### Start from relevance between python and CPP class
Currently, the instantiation process of CPP class objects by a Python class 
remains unclear. However, by examining the constructor function of the CPP class 
and the attributes of the Python class, we can make an informed assumption that 
the Python class is likely associated with the parameters needed for instantiating 
the CPP class object. Let's explore this further!

> CPP implementation of System class
{: .prompt-info}

```python
class System(SimObject):
    type = 'System'
    cxx_header = "sim/system.hh"
    system_port = RequestPort("System port")

    cxx_exports = [
        PyBindMethod("getMemoryMode"),
        PyBindMethod("setMemoryMode"),
    ]

    memories = VectorParam.AbstractMemory(Self.all,
                                          "All memories in the system")
    mem_mode = Param.MemoryMode('atomic', "The mode the memory system is in")

    thermal_model = Param.ThermalModel(NULL, "Thermal model")
    thermal_components = VectorParam.SimObject([],
            "A collection of all thermal components in the system.")

    # When reserving memory on the host, we have the option of
    # reserving swap space or not (by passing MAP_NORESERVE to
    # mmap). By enabling this flag, we accommodate cases where a large
    # (but sparse) memory is simulated.
    mmap_using_noreserve = Param.Bool(False, "mmap the backing store " \
                                          "without reserving swap")

    # The memory ranges are to be populated when creating the system
    # such that these can be passed from the I/O subsystem through an
    # I/O bridge or cache
    mem_ranges = VectorParam.AddrRange([], "Ranges that constitute main memory")

    shared_backstore = Param.String("", "backstore's shmem segment filename, "
        "use to directly address the backstore from another host-OS process. "
        "Leave this empty to unset the MAP_SHARED flag.")

    cache_line_size = Param.Unsigned(64, "Cache line size in bytes")
    ......
```

> Python implementation of System class
```cpp
System::System(Params *p)
    : SimObject(p), _systemPort("system_port", this),
      multiThread(p->multi_thread),
      pagePtr(0),
      init_param(p->init_param),
      physProxy(_systemPort, p->cache_line_size),
      workload(p->workload),
#if USE_KVM
      kvmVM(p->kvm_vm),
#else
      kvmVM(nullptr),
#endif
      physmem(name() + ".physmem", p->memories, p->mmap_using_noreserve,
              p->shared_backstore),
      memoryMode(p->mem_mode),
      _cacheLineSize(p->cache_line_size),
      workItemsBegin(0),
      workItemsEnd(0),
      numWorkIds(p->num_work_ids),
      thermalModel(p->thermal_model),
      _params(p),
      _m5opRange(p->m5ops_base ?
                 RangeSize(p->m5ops_base, 0x10000) :
                 AddrRange(1, 0)), // Create an empty range if disabled
      totalNumInsts(0),
      redirectPaths(p->redirect_paths)
{
```

As an illustration, consider the attribute "cache_line_size" within the Python 
class. This attribute not only exists within the Python class but is also employed
to initialize a \_cacheLineSize member field of the CPP System class. Note that 
this attribute is accessed through the Param struct, which encapsulates all the 
configuration details of the hardware module necessary for instantiating it as a 
CPP class object.

### Automatic Param generation 
From the example, you might grab the idea of python script. It provides hardware 
configurations to instantiate hardware component for simulation! As each hardware
component may need distinctive configurations, like cache line size or the number 
of buffer entries, Python classes gather all pertinent hardware configuration 
details and transmit them to the CPP implementation through the Param struct.
Nevertheless, the CPP Param struct passed to the System constructor is not 
explicitly present in the codebase. This absence is attributed to the automatic 
generation of the Param struct for instantiating the System class object, 
transitioning seamlessly from Python class to CPP struct. Let's examine the 
the automatically generated struct to gain a comprehensive understanding.

```cpp
struct SystemParams
    : public SimObjectParams
{
    System * create();
    ByteOrder byte_order;
    unsigned cache_line_size;
    bool exit_on_work_items;
    uint64_t init_param;
    KvmVM * kvm_vm;
    Addr m5ops_base;
    Enums::MemoryMode mem_mode;
    std::vector< AddrRange > mem_ranges;
    std::vector< AbstractMemory * > memories;
    bool mmap_using_noreserve;
    bool multi_thread;
    int num_work_ids;
    std::string readfile;
    std::vector< RedirectPath * > redirect_paths;
    std::string shared_backstore;
    std::string symbolfile;
    std::vector< SimObject * > thermal_components;
    ThermalModel * thermal_model;
    Counter work_begin_ckpt_count;
    int work_begin_cpu_id_exit;
    Counter work_begin_exit_count;
    Counter work_cpus_ckpt_count;
    Counter work_end_ckpt_count;
    Counter work_end_exit_count;
    int work_item_id;
    Workload * workload;
    unsigned int port_system_port_connection_count;
};
```

The SystemParams struct is automatically created and supplied to the constructor
of the System class, facilitating the initialization of hardware parameters for 
the System component. Furthermore, the generated struct contains member fields 
that correspond to certain attributes of the System class in Python. I will 
explain which attributes of the python classes can be translated into CPP counter
parts soon. Please bear with me!

#### Automatic pybind generation
As the generated struct is implemented in CPP, it needs to be exported to Python
so that it can configure the parameters based on the information provided by the
Python configuration script.

```cpp
static void
module_init(py::module &m_internal)
{
    py::module m = m_internal.def_submodule("param_System");
    py::class_<SystemParams, SimObjectParams, std::unique_ptr<SystemParams, py::nodelete>>(m, "SystemParams")
        .def(py::init<>())
        .def("create", &SystemParams::create)
        .def_readwrite("byte_order", &SystemParams::byte_order)
        .def_readwrite("cache_line_size", &SystemParams::cache_line_size)
        .def_readwrite("exit_on_work_items", &SystemParams::exit_on_work_items)
        .def_readwrite("init_param", &SystemParams::init_param)
        .def_readwrite("kvm_vm", &SystemParams::kvm_vm)
        .def_readwrite("m5ops_base", &SystemParams::m5ops_base)
        .def_readwrite("mem_mode", &SystemParams::mem_mode)
        .def_readwrite("mem_ranges", &SystemParams::mem_ranges)
        .def_readwrite("memories", &SystemParams::memories)
        .def_readwrite("mmap_using_noreserve", &SystemParams::mmap_using_noreserve)
        .def_readwrite("multi_thread", &SystemParams::multi_thread)
        .def_readwrite("num_work_ids", &SystemParams::num_work_ids)
        .def_readwrite("readfile", &SystemParams::readfile)
        .def_readwrite("redirect_paths", &SystemParams::redirect_paths)
        .def_readwrite("shared_backstore", &SystemParams::shared_backstore)
        .def_readwrite("symbolfile", &SystemParams::symbolfile)
        .def_readwrite("thermal_components", &SystemParams::thermal_components)
        .def_readwrite("thermal_model", &SystemParams::thermal_model)
        .def_readwrite("work_begin_ckpt_count", &SystemParams::work_begin_ckpt_count)
        .def_readwrite("work_begin_cpu_id_exit", &SystemParams::work_begin_cpu_id_exit)
        .def_readwrite("work_begin_exit_count", &SystemParams::work_begin_exit_count)
        .def_readwrite("work_cpus_ckpt_count", &SystemParams::work_cpus_ckpt_count)
        .def_readwrite("work_end_ckpt_count", &SystemParams::work_end_ckpt_count)
        .def_readwrite("work_end_exit_count", &SystemParams::work_end_exit_count)
        .def_readwrite("work_item_id", &SystemParams::work_item_id)
        .def_readwrite("workload", &SystemParams::workload)
        .def_readwrite("port_system_port_connection_count", &SystemParams::port_system_port_connection_count)
        ;

    py::class_<System, SimObject, std::unique_ptr<System, py::nodelete>>(m, "System")
        .def("getMemoryMode", &System::getMemoryMode)
        .def("setMemoryMode", &System::setMemoryMode)
        ;

}

static EmbeddedPyBind embed_obj("System", module_init, "SimObject");
```

As illustrated in the provided code, GEM5 automatically generates "module_init" 
function that utilizes the pybind library to export the automatically generated 
Param struct and its member fields to Python. Additionally, it creates an 
EmbeddedPyBind object to register the automatically generated module_init 
function to the object. 
The module_init function is responsible for exporting the CPP implementation to
Python, falling into the second category outlined in 
[Pybind Initialization for HW components](#pybind-initialization-for-hw-components).
Now you can understand why GEM5 main function exports the CPP implementation 
in two different ways. 


## SimObject Python class
To understand how GEM5 automatically generate CPP Param struct and its pybind 
from Python classes, we should understand SimObject class and MetaSimObject 
metaclass. In GEM5, a SimObject represents a simulation entity and forms the 
basis for modeling components within the system being simulated. In other words, 
all system component related classes instantiated in the Python configuration 
script should be inherited from the SimObject class. 

```python
# gem5/src/Python/m5/SimbObject.py

@add_metaclass(MetaSimObject)
class SimObject(object):
    # Specify metaclass.  Any class inheriting from SimObject will
    # get this metaclass.
    type = 'SimObject'
    abstract = True
```

Although SimObject is the fundamental building block of GEM5 simulation in 
defining hardware components, its metaclass, MetaSibObject is the most important
in terms of bridging Python to CPP. 

### MetaSimObject: metaclass of SimObject 
When one Python class has metaclass, functions defined in metaclass can 
pre-process newly defined class. For example, attributes of Python class having 
metaclass can be audited by metaclasss functions such as '__init__, __new__ or, 
__call__'. Since metaclass can access class and its attributes (dictionary), it 
can modify or introduce particular attribute and logic during the class 
instantiation. For further details of metaclass, please refer to 
[Python-metaclass](https://realPython.com/Python-metaclasses/).


```python
#src/Python/m5/SimObject.py

class MetaSimObject(type):
    # Attributes that can be set only at initialization time
    init_keywords = {
        'abstract' : bool,
        'cxx_class' : str,
        'cxx_type' : str,
        'cxx_header' : str,
        'type' : str,
        'cxx_base' : (str, type(None)),
        'cxx_extra_bases' : list,
        'cxx_exports' : list,
        'cxx_param_exports' : list,
        'cxx_template_params' : list,
    }
    # Attributes that can be set any time
    keywords = { 'check' : FunctionType }
```

## Generate CPP Param struct and its pybind 
Examining the Python class for System reveals the presence of certain Python 
attributes unrelated to the CPP System class. Our task is to selectively filter 
out only those Python class attributes essential for instantiating their CPP 
class counterparts. If the notion of Python metaclass comes to mind, there's no
need for an in-depth exploration. As mentioned earlier, Python metaclass provides
access to all attributes of a class that has it as a metaclass, making it an 
ideal location to efficiently **filter and extract only the necessary attributes.**

Before delving into how the metaclass aids in filtering out only the relevant 
attributes from the Python class, let's first examine the Python code responsible 
for automatically generating the Param struct. This will provide insight into 
which attributes of the Python classes need to be filtered out to generate CPP 
code. Given that many Python-based automatic code generation processes involve 
string manipulation and substitution, locating the function can be done by 
searching for relevant logic within the generated CPP code.

<a name="cxx-param-decl"></a>
```python
    def cxx_param_decl(cls, code):
        params = list(map(lambda k_v: k_v[1], sorted(cls._params.local.items())))
        ports = cls._ports.local
        ......
        if cls == SimObject:
            code('''#include <string>''')
        
        cxx_class = CxxClass(cls._value_dict['cxx_class'],
                             cls._value_dict['cxx_template_params'])
        
        # A forward class declaration is sufficient since we are just
        # declaring a pointer.
        cxx_class.declare(code)
        
        for param in params:
            param.cxx_predecls(code)
        for port in ports.values():
            port.cxx_predecls(code)
        code()
        
        if cls._base:
            code('#include "params/${{cls._base.type}}.hh"')
            code()
        
        for ptype in ptypes:
            if issubclass(ptype, Enum):
                code('#include "enums/${{ptype.__name__}}.hh"')
                code()
        
        # now generate the actual param struct
        code("struct ${cls}Params")
        if cls._base:
            code("    : public ${{cls._base.type}}Params")
        code("{")
        if not hasattr(cls, 'abstract') or not cls.abstract:
            if 'type' in cls.__dict__:
                code("    ${{cls.cxx_type}} create();")
        
        code.indent()
        if cls == SimObject:
            code('''
    SimObjectParams() {}
    virtual ~SimObjectParams() {}

    std::string name;
            ''')
        
        for param in params:
            param.cxx_decl(code)
        for port in ports.values():
            port.cxx_decl(code)
        
        code.dedent()
        code('};')
```
By comparing the code above with the automatically generated struct, it will 
become apparent which sections of the Python code correspond to the which parts
of the CPP implementation. Presented below is the Python code responsible for 
generating the CPP function (i.e., module_init) that exports the automatically 
generated struct to Python through pybind.

```python
    def pybind_predecls(cls, code):
        code('#include "${{cls.cxx_header}}"')
    
    def pybind_decl(cls, code):
        py_class_name = cls.pybind_class
        
        # The 'local' attribute restricts us to the params declared in
        # the object itself, not including inherited params (which
        # will also be inherited from the base class's param struct
        # here). Sort the params based on their key
        params = list(map(lambda k_v: k_v[1], sorted(cls._params.local.items())))
        ports = cls._ports.local
        
        code('''#include "pybind11/pybind11.h"
#include "pybind11/stl.h"

#include "params/$cls.hh"
#include "Python/pybind11/core.hh"
#include "sim/init.hh"
#include "sim/sim_object.hh"

#include "${{cls.cxx_header}}"

''')    
        
        for param in params:
            param.pybind_predecls(code)
        
        code('''namespace py = pybind11;

static void
module_init(py::module &m_internal)
{
    py::module m = m_internal.def_submodule("param_${cls}");
''')    
        code.indent()
        if cls._base:
            code('py::class_<${cls}Params, ${{cls._base.type}}Params, ' \
                 'std::unique_ptr<${{cls}}Params, py::nodelete>>(' \
                 'm, "${cls}Params")')
        else:
            code('py::class_<${cls}Params, ' \
                 'std::unique_ptr<${cls}Params, py::nodelete>>(' \
                 'm, "${cls}Params")')
        
        code.indent()
        if not hasattr(cls, 'abstract') or not cls.abstract:
            code('.def(py::init<>())')
            code('.def("create", &${cls}Params::create)')
        
        param_exports = cls.cxx_param_exports + [
            PyBindProperty(k)
            for k, v in sorted(cls._params.local.items())
        ] + [
            PyBindProperty("port_%s_connection_count" % port.name)
            for port in ports.values()
        ]
        for exp in param_exports:
            exp.export(code, "%sParams" % cls)
```


```python
class PyBindProperty(PyBindExport):
    def __init__(self, name, cxx_name=None, writable=True):
        self.name = name
        self.cxx_name = cxx_name if cxx_name else name
        self.writable = writable
        
    def export(self, code, cname):
        export = "def_readwrite" if self.writable else "def_readonly"
        code('.${export}("${{self.name}}", &${cname}::${{self.cxx_name}})')
```

Upon a thorough comparison of the automatically generated code and the 
corresponding Python code, it becomes evident that attributes instantiated as 
instances of Port and Param play a crucial role in both generating the CPP 
implementation of the Param struct and facilitating its pybind integration.


### __init__ of MetaSimObject
From the Python code template, it becomes clear that attributes related to Param 
and Port are crucial for automatically generating the Param struct and its pybind 
integration. The next step is to determine how to selectively filter out the
attributes relevant to Param and Port from the classes associated with each 
hardware component. This is where SimObject becomes useful. We will explore how 
a metaclass aids in filtering out attributes related to Param and Port from 
Python classes that inherit from SimObject.

```python
    def __init__(cls, name, bases, dict):                                       
        super(MetaSimObject, cls).__init__(name, bases, dict)                   
                                                                                
        # initialize required attributes                                        
                                                                                
        # class-only attributes                                                 
        cls._params = multidict() # param descriptions                          
        cls._ports = multidict()  # port descriptions                           
                                                                                
        cls._deprecated_params = multidict()                                    
                                                                                
        # class or instance attributes                                          
        cls._values = multidict()   # param values                              
        cls._hr_values = multidict() # human readable param values              
        cls._children = multidict() # SimObject children                        
        cls._port_refs = multidict() # port ref objects                         
        cls._instantiated = False # really instantiated, cloned, or subclassed  
                                                                                
        ......
        for key,val in cls._value_dict.items():                                 
            # param descriptions                                                
            if isinstance(val, ParamDesc):                                      
                cls._new_param(key, val)                                        
                                                                                
            # port objects                                                      
            elif isinstance(val, Port):                                         
                cls._new_port(key, val)                                         
                                                                                
            # Deprecated variable names                                         
            elif isinstance(val, DeprecatedParam):                              
                new_name, new_val = cls._get_param_by_value(val.newParam)       
                # Note: We don't know the (string) name of this variable until  
                # here, so now we can finish setting up the dep_param.          
                val.oldName = key                                               
                val.newName = new_name                                          
                cls._deprecated_params[key] = val                               
                                                                                
            # init-time-only keywords                                           
            elif key in cls.init_keywords:                                      
                cls._set_keyword(key, val, cls.init_keywords[key])              
                                                                                
            # default: use normal path (ends up in __setattr__)                 
            else:                                                               
                setattr(cls, key, val)     

```
The MetaSimObject metaclass's above __init__ function is triggered for any Python 
classes inheriting SimObject, thanks to SimObject setting MetaSimObject as its 
metaclass. This function iterates through all attributes in the class and checks
if it is an instance of either ParamDesc or Port. Depending on the instance type, 
it invokes '_new_param' or 'new_port,' placing the attribute in the '_params' or 
'_ports' dictionary of the class. In essence, this process effectively filters 
out and organizes these two types of attributes in their respective dictionaries.

```python
    def _new_param(cls, name, pdesc):
        # each param desc should be uniquely assigned to one variable
        assert(not hasattr(pdesc, 'name'))
        pdesc.name = name
        cls._params[name] = pdesc
        if hasattr(pdesc, 'default'):
            cls._set_param(name, pdesc.default, pdesc)

    def _new_port(cls, name, port):
        # each port should be uniquely assigned to one variable
        assert(not hasattr(port, 'name'))
        port.name = name
        cls._ports[name] = port

```

Upon revisiting the [code](#generate-cpp-param-struct-and-its-pybind), you can
discern the utilization of the newly introduced dictionaries as keys in
automatically generating the CPP implementation for the Param struct and its 
corresponding pybind code. 


### Type sensitive Python Params
Python Param class is a placeholder for any parameter that should be translated 
into CPP from Python attribute. Compared with Python which doesn't need a strict
type for attribute, CPP need clear and distinct type for all variables. Therefore,
to translate Python attribute to CPP variable, GEM5 should manage value and type
altogether, which is achieved by ParamDesc class. 

```python
# Python/m5/params.py

class ParamDesc(object):
    def cxx_decl(self, code):
        code('${{self.ptype.cxx_type}} ${{self.name}};')
```

The 'cxx_decl' method is called during GEM5's process of automatically converting 
Python attributes (instances of ParamDesc) into CPP variables in the cxx_param_decl
function. As depicted in the code, it retrieves the CPP type from the
'self.ptype.cxx_type' and its name from 'self.name'. We will take a look at how 
Param related python classes manages those two attributes. You might wonder why
it is ParamDesc not Param previously used to define attributes in Python class.

```python
Param = ParamFactory(ParamDesc)
```

The trick is assigning another class ParamFactory to Param so that developer 
can easily instantiate ParamDesc object per attribute, required for generating 
CPP class parameter. 

```python
class ParamFactory(object):
    def __init__(self, param_desc_class, ptype_str = None):
        self.param_desc_class = param_desc_class
        self.ptype_str = ptype_str
    
    def __getattr__(self, attr):
        if self.ptype_str:
            attr = self.ptype_str + '.' + attr
        return ParamFactory(self.param_desc_class, attr)
    
    def __call__(self, *args, **kwargs):
        ptype = None
        try:
            ptype = allParams[self.ptype_str]
        except KeyError:
            # if name isn't defined yet, assume it's a SimObject, and
            # try to resolve it later
            pass
        return self.param_desc_class(self.ptype_str, ptype, *args, **kwargs)
```

As Python lacks a type that can directly correspond to C++ types on a one-to-one 
basis, it employs various Python classes to represent C++ types that the Param 
should be translated into. Let's explore how the ParamFactory and ParamDesc can
be used to generate a Python class object representing specific C++ types.

```python
    cache_line_size = Param.Unsigned(64, "Cache line size in bytes")
```


The right-hand side of the assignment appears simple at first glance, but it 
involves multiple function invocations in detail. Initially, the interpretation 
of Param is as ParamFactory(ParamDesc), resulting in a ParamFactory object with 
'param_desc_class' set to 'ParamDesc'. This returned object is then utilized to
access its 'Unsigned' attribute. As it defines the '__getattr__' function, this 
function is invoked instead of directly accessing the 'Unsigned' attribute. 
Consequently, it generates another ParamFactory object with 'param_desc_class'
set to 'ParamDesc' and 'ptype_str' set to 'Unsigned'. The parentheses following 
the ParamFactory object are interpreted as a function call, leading to the 
invocation of the '__call__' method. While allParams is not yet known, it returns
the class that matches ptype_str ('Unsigned'). Subsequently, it returns a 
ParamDesc object initialized with "Unsigned" and the class matching with the 
pytype_str. 

Then how GEM5 generates dictionary mapping ptype_str to class object
associated with the string? To manage allParams dictionary, GEM5 utilize another 
Python metaclass, MetaParamValue.


```python
class MetaParamValue(type):
    def __new__(mcls, name, bases, dct):
        cls = super(MetaParamValue, mcls).__new__(mcls, name, bases, dct)
        if name in allParams:
            warn("%s already exists in allParams. This may be caused by the " \
                 "Python 2.7 compatibility layer." % (name, ))
        allParams[name] = cls
        return cls 
```

As shown in the '__new__' function of the metaclass,it produces an 'allParams' 
dictionary that can be accessed using its class name and returns the corresponding 
class object. Consequently, Python classes intended for translating the 'Param'
attribute to the appropriate CPP type implementation should designate 
'MetaParamValue' as their metaclass.


```python
class Unsigned(CheckedInt): cxx_type = 'unsigned'; size = 32; unsigned = True

class CheckedIntType(MetaParamValue):
    def __init__(cls, name, bases, dict):
        super(CheckedIntType, cls).__init__(name, bases, dict)
    
        # CheckedInt is an abstract base class, so we actually don't
        # want to do any processing on it... the rest of this code is
        # just for classes that derive from CheckedInt.
        if name == 'CheckedInt':
            return

        if not (hasattr(cls, 'min') and hasattr(cls, 'max')):
            if not (hasattr(cls, 'size') and hasattr(cls, 'unsigned')):
                panic("CheckedInt subclass %s must define either\n" \
                      "    'min' and 'max' or 'size' and 'unsigned'\n",
                      name);
            if cls.unsigned:
                cls.min = 0
                cls.max = 2 ** cls.size - 1
            else:
                cls.min = -(2 ** (cls.size - 1))
                cls.max = (2 ** (cls.size - 1)) - 1

```


As indicated in the class definition, the 'Unsigned' class inherits from 
'CheckedIntType,' which designates 'MetaParamValue' as its metaclass. 
Consequently, during the initialization of the 'Unsigned' class, it will call
the '__new__' function of the 'MetaParamValue' metaclass, creating a mapping from
the string 'Unsigned' to the class object 'Unsigned' in the 'allParams'.
Therefore, in the preceding code, the 'ptype' returned from 'allParams' should
be an object of the 'Unsigned' class. In summary, the RHS of the assignment 
will be 

> ParamDesc("Unsigned", Unsigned class object, *args, **kwargs)

Therefore the cache_line_size will have the ParamDesc class object instantiated
by the code block. 

```cpp
class ParamDesc(object):
    def __init__(self, ptype_str, ptype, *args, **kwargs):
        self.ptype_str = ptype_str
        # remember ptype only if it is provided
        if ptype != None:
            self.ptype = ptype

        if args:
            if len(args) == 1:
                self.desc = args[0]
            elif len(args) == 2:
                self.default = args[0]
                self.desc = args[1]
            else:
                raise TypeError('too many arguments')
        ......
```

The passed string and class object are stored in the ParamDesc attributes and 
will be used to generate the CPP type!

## Python Port describes connectivity
While going through Params and its pybind, you may have noticed that 
MetaSimObject filter out Port attributes from Python classes separately as well
as the ParamDesc instance. Given that GEM5 serves as a comprehensive system 
simulator, it necessitates not only diverse hardware elements like CPU and 
memory controllers that make up the platform but also the interconnecting wires
facilitating communication between these hardware components. Given that the 
communication medium functions as a hardware component, GEM5 simulates it just 
like any other hardware components in the system.

Moreover, as well as the Python classes are utilized to provide parameters of 
hardware components and instantiate the simulation for each hardware component 
implemented in CPP, the connectivity presented in Python code should be translated 
into CPP and generate connection between CPP class objects. Therefore, we need 
to understand how this transformation happens.

### How Python script establish the connection?
Let's see how Python script generates connection between two different hardware
components through the port. 

```python
# create the system we are going to simulate
system = System()

# Create a memory bus, a system crossbar, in this case
system.membus = SystemXBar()

# Connect the system up to the membus
system.system_port = system.membus.slave
```

```python
class System(SimObject):                                                        
    type = 'System'                                                             
    cxx_header = "sim/system.hh"                                                
    system_port = RequestPort("System port")   

class Port(object):
    ......
    def __init__(self, role, desc, is_source=False):
        self.desc = desc
        self.role = role
        self.is_source = is_source
    ......


class RequestPort(Port):
    # RequestPort("description")
    def __init__(self, desc):
        super(RequestPort, self).__init__(
                'GEM5 REQUESTOR', desc, is_source=True)

class ResponsePort(Port):
    # ResponsePort("description")
    def __init__(self, desc):
        super(ResponsePort, self).__init__('GEM5 RESPONDER', desc)
```
As illustrated in the Python script, it sets up the configuration for the System
and SystemXBar, creating a connection between them by linking the Response port 
(SystemXBar.slave) to the Request port (System.system_port). While this may 
appear as a straightforward assignment, there are intricate details underlying 
the support for Port assignment. To grasp this, it's essential to recall that
all hardware component classes inherit from SimObject. The SimObject class 
defines the __getattr__ and __setattr__ functions to control attribute access
and assignment. Let's delve into each of these details in turn.

```python
    def __setattr__(self, attr, value):
        # normal processing for private attributes
        if attr.startswith('_'):
            object.__setattr__(self, attr, value)
            return
        
        if attr in self._deprecated_params:
            dep_param = self._deprecated_params[attr]
            dep_param.printWarning(self._name, self.__class__.__name__) 
            return setattr(self, self._deprecated_params[attr].newName, value)
        
        if attr in self._ports:
            # set up port connection
            self._get_port_ref(attr).connect(value)
            return
        
        param = self._params.get(attr)
        if param:
            try:
                hr_value = value
                value = param.convert(value)
            except Exception as e:
                msg = "%s\nError setting param %s.%s to %s\n" % \
                      (e, self.__class__.__name__, attr, value)
                e.args = (msg, )
                raise
            self._values[attr] = value
            # implicitly parent unparented objects assigned as params
            if isSimObjectOrVector(value) and not value.has_parent():
                self.add_child(attr, value)
            # set the human-readable value dict if this is a param
            # with a literal value and is not being set as an object
            # or proxy.
            if not (isSimObjectOrVector(value) or\
                    isinstance(value, m5.proxy.BaseProxy)):
                self._hr_values[attr] = hr_value
            
            return
        
        # if RHS is a SimObject, it's an implicit child assignment
        if isSimObjectOrSequence(value):
            self.add_child(attr, value)
            return
        
        # no valid assignment... raise exception
        raise AttributeError("Class %s has no parameter %s" \
              % (self.__class__.__name__, attr))

```

To understand the reference system.membus.slave, it's crucial to grasp how membus 
becomes an attribute of the System. Given that there is no statically predefined 
attribute named membus in the System class, it is dynamically added to the System
class object during runtime. The __setattr__ function in the SimObject class 
comes into play when a new attribute is introduced to the object. Since the added 
value is another SimObject class object obtained from SystemXBar(), it is treated
as a child of the System. 


```python
    # Add a new child to this object.
    def add_child(self, name, child):
        child = coerceSimObjectOrVector(child)
        if child.has_parent():
            warn("add_child('%s'): child '%s' already has parent", name,
                child.get_name())
        if name in self._children:
            # This code path had an undiscovered bug that would make it fail
            # at runtime. It had been here for a long time and was only
            # exposed by a buggy script. Changes here will probably not be
            # exercised without specialized testing.
            self.clear_child(name)
        child.set_parent(self, name)
        if not isNullPointer(child):
            self._children[name] = child
```
Recall my earlier mention that SimObject can be structured hierarchically. 
Considering that the System class represents the entire simulated system, it 
follows logically that the crossbar connecting hardware components in the system
should be a child of the System. Now, let's explore the outcome when attempting 
to access system.membus.slave!

```python
    def __getattr__(self, attr):
        if attr in self._deprecated_params:
            dep_param = self._deprecated_params[attr]
            dep_param.printWarning(self._name, self.__class__.__name__)
            return getattr(self, self._deprecated_params[attr].newName)
        
        if attr in self._ports:
            return self._get_port_ref(attr)
        
        if attr in self._values:
            return self._values[attr]
        
        if attr in self._children:
            return self._children[attr]
        
        # If the attribute exists on the C++ object, transparently
        # forward the reference there.  This is typically used for
        # methods exported to Python (e.g., init(), and startup())
        if self._ccObject and hasattr(self._ccObject, attr):
            return getattr(self._ccObject, attr)
        
        err_string = "object '%s' has no attribute '%s'" \
              % (self.__class__.__name__, attr)
        
        if not self._ccObject:
            err_string += "\n  (C++ object is not yet constructed," \
                          " so wrapped C++ methods are unavailable.)"
        
        raise AttributeError(err_string)
```

The access is accomplished through two calls to the `__getattr__` method. It can
be conceptualized as '(system.membus).slave'. Since System is a SimObject, and
the SimObject class defines the `__getattr__` function, this function is
automatically invoked to access the `membus` attribute. As `membus` has been
registered as a child of the system, the SystemXBar class object is retrieved
first. Additionally, since it is a SimObject, when the `slave` attribute is
accessed, it triggers another `__getattr__` function. As the `slave` attribute is
declared as a Port in the BaseXBar class, which is the base Python class of
SystemXBar, it should have been filtered out as '_ports' when the SystemXBar is
defined, thanks to the metaclass. Therefore, when an attribute related to Port
is accessed, it invokes '_get_port_ref' to return a reference to that port.


### PortRef, connecting two end ports 

```cpp
    def _get_port_ref(self, attr):
        # Return reference that can be assigned to another port
        # via __setattr__.  There is only ever one reference
        # object per port, but we create them lazily here.
        ref = self._port_refs.get(attr)
        if ref == None:
            ref = self._ports[attr].makeRef(self)
            self._port_refs[attr] = ref
        return ref 
```

SimObject has cache for reference of Port, self._port_refs. If it is the first
time to access this attribute, then the cache should be empty and will invoke
makeRef function of the system_port object. 

```python
class Port(object):                                                             
    ......
    # Port("role", "description") 
    # Generate a PortRef for this port on the given SimObject with the          
    # given name                                                                
    def makeRef(self, simobj):                                                  
        return PortRef(simobj, self.name, self.role, self.is_source)  

```
makeRef creates an instance of PortRef, where Port serves as a wrapper class 
that conveys information about the port, and the actual reference to the Port is
defined by the PortRef class. The retrieved PortRef instance is then stored in 
the '_ports' attribute of the SimObject. This storage will later be employed to 
transfer the Python-presented connectivity between the hardware components to
C++. Regardless, the right-hand side of the assignment is transformed into an 
object of PortRef. Assigning it to 'system.system_port' on the left-hand side
triggers another 'setattr' within the SimObject!

```python
        if attr in self._ports:                                                 
            # set up port connection                                            
            self._get_port_ref(attr).connect(value)                             
            return                     
```
At this point, since 'system_port' is an instance of a Port class, this attribute
must exist in the '_ports' dictionary. When considering the assignment in terms 
of ports logically, it should establish a connection between two hardware
components. To accomplish this, it effectively invokes the 'connect' function!
Given that '_get_port_ref' returns another PortRef for the 'system_port', it
proceeds to connect the PortRef of 'system_port' and 'slave'.

```python
class PortRef(object): 
    def connect(self, other):
        if isinstance(other, VectorPortRef):
            # reference to plain VectorPort is implicit append
            other = other._get_next()
        if self.peer and not proxy.isproxy(self.peer):
            fatal("Port %s is already connected to %s, cannot connect %s\n",
                  self, self.peer, other);
        self.peer = other

        if proxy.isproxy(other):
            other.set_param_desc(PortParamDesc())
            return
        elif not isinstance(other, PortRef):
            raise TypeError("assigning non-port reference '%s' to port '%s'" \
                  % (other, self))

        if not Port.is_compat(self, other):
            fatal("Ports %s and %s with roles '%s' and '%s' "
                    "are not compatible", self, other, self.role, other.role)

        if other.peer is not self:
            other.connect(self)
```

## SConscript: generating files for CPP implementation 
Now we can understand where the Python code is located and how the data required
for generating CPP implementation can be gathered from each Python class. Then,
some program should invoke the Python method to generate actual CPP and header
file containing automatically generated CPP implementation. That is done at the 
compile time by scone. SCons is a build automation tool that uses Python scripts
for configuration and build control. 


```python
# gem5/src/SConscript

# Generate all of the SimObject param C++ struct header files
params_hh_files = []
for name,simobj in sorted(sim_objects.items()):
    # If this simobject's source changes, we need to regenerate the header.
    py_source = PySource.modules[simobj.__module__]
    extra_deps = [ py_source.tnode ]
    
    # Get the params for just this SimObject, excluding base classes.
    params = simobj._params.local.values()
    # Extract the parameters' c++ types.
    types = sorted(map(lambda p: p.ptype.cxx_type, params))
    # If any of these types have changed, we need to regenerate the header.
    extra_deps.append(Value(types))
    
    hh_file = File('params/%s.hh' % name)
    params_hh_files.append(hh_file)
    env.Command(hh_file, Value(name),
                MakeAction(createSimObjectParamStruct, Transform("SO PARAM")))
    env.Depends(hh_file, depends + extra_deps)


def createSimObjectParamStruct(target, source, env):
    assert len(target) == 1 and len(source) == 1

    name = source[0].get_text_contents()
    obj = sim_objects[name]

    code = code_formatter()
    obj.cxx_param_decl(code)
    code.write(target[0].abspath)

# Generate SimObject Python bindings wrapper files
if env['USE_PYTHON']:
    for name,simobj in sorted(sim_objects.iteritems()):
        py_source = PySource.modules[simobj.__module__]
        extra_deps = [ py_source.tnode ]
        cc_file = File('Python/_m5/param_%s.cc' % name)
        env.Command(cc_file, Value(name),
                    MakeAction(createSimObjectPyBindWrapper,
                               Transform("SO PyBind")))
        env.Depends(cc_file, depends + extra_deps)
        Source(cc_file)

def createSimObjectPyBindWrapper(target, source, env):
    name = source[0].get_text_contents()
    obj = sim_objects[name]

    code = code_formatter()
    obj.pybind_decl(code)
    code.write(target[0].abspath)
```

When you take a look at the main SConScript located in the root src directory,
there are two locations invoking Python methods that you must be familiar with
(obj.pybind_decl and obj.cxx_param_decl). One thing not clear in the SConscript 
is **sim_objects**. 

```python
# gem5/src/SConscript  

sim_objects = m5.SimObject.allClasses
```

In the SConscript, it is defined as attribute from m5.SibObject Python module. 
Then what is allClasses? The answer is in the MetaSimObject!

```python
# Python/m5/SimObject.py

# list of all SimObject classes
allClasses = {}

class MetaSimObject(type):
    def __new__(mcls, name, bases, dict):
        assert name not in allClasses, "SimObject %s already present" % name
        
        # Copy "private" attributes, functions, and classes to the
        # official dict.  Everything else goes in _init_dict to be
        # filtered in __init__.
        cls_dict = {}
        value_dict = {}
        cxx_exports = []

        ......

        cls = super(MetaSimObject, mcls).__new__(mcls, name, bases, cls_dict)
        if 'type' in value_dict:
            allClasses[name] = cls
        return cls
```
As depicted in the above code, the __new__ method generate dictionary consisting
of its name and actual class object and assign it to allClasses attribute in the
m5.SimObject. However, to make MetaSimObject to invoke __new__ method for all
Python classes inheriting from SimObject and fill out allClasses dictionary,
all Python classes should be imported first. 


```python
class SimObject(PySource):
    '''Add a SimObject Python file as a Python source object and add
    it to a list of sim object modules'''

    fixed = False
    modnames = []

    def __init__(self, source, tags=None, add_tags=None):
        '''Specify the source file and any tags (automatically in
        the m5.objects package)'''
        super(SimObject, self).__init__('m5.objects', source, tags, add_tags)
        if self.fixed:
            raise AttributeError("Too late to call SimObject now.")

        bisect.insort_right(SimObject.modnames, self.modname)

for modname in SimObject.modnames:
    exec('from m5.objects import %s' % modname)
```

To import relevant Python classes, root SConscript defines SimObject class and 
import the classes to the Python environment where SConscript is being executed. 

> Note that SimObject class is not identical to SimObject class having
> MetaSimObject as its metaclass used for defining simulated components. 

Then who instantiates above SimObjects? SConscript can exist in subdirectories 
to handle the build details. Let's take a look at the sub-directory containing 
Python code defining Python classes inheriting SimObject. 


```python
# /gem5/src/sim/SConscript

Import('*')

SimObject('ClockedObject.py')
SimObject('TickedObject.py')
SimObject('Workload.py')
SimObject('Root.py')
SimObject('ClockDomain.py')
SimObject('VoltageDomain.py')
SimObject('System.py')
SimObject('DVFSHandler.py')
SimObject('SubSystem.py')
SimObject('RedirectPath.py')
SimObject('PowerState.py')
SimObject('PowerDomain.py')
```

As shown in the above script, it instantiates SimObject to import Python classes
defining hardware simulation building block. You might wonder how this exported 
CPP implementation can be utilized by Python classes, but please bear with me!
I will give you details after covering Port!


## Python to CPP transformation 
Whoa! It was quite intense because GEM5 heavily relies on Python classes to
represent and organize hardware components. However, the most crucial question
remains unanswered! As Python serves merely as a wrapper for CPP classes used
in the actual simulation, the configuration specified in Python must be
translated into CPP implementation, encompassing the instantiation of CPP
classes and the establishment of connections between them.


```python
# set up the root SimObject and start the simulation
root = Root(full_system = False, system = system)
# instantiate all of the objects we've created above
m5.instantiate()
```

When you finish configuration, you should instantiate Root class and invoke 
'instantiate' function to transform your Python configurations into CPP 
implementation.


```python
class Root(SimObject):
    
    _the_instance = None

    def __new__(cls, **kwargs):
        if Root._the_instance:
            fatal("Attempt to allocate multiple instances of Root.")
            return None

        Root._the_instance = SimObject.__new__(cls)
        return Root._the_instance

    @classmethod
    def getInstance(cls):
        return Root._the_instance
    

    type = 'Root'
    cxx_header = "sim/root.hh"
                      
    # By default, root sim object and hence all other sim objects schedule
    # event on the eventq with index 0.
    eventq_index = 0

    # Simulation Quantum for multiple main event queue simulation.
    # Needs to be set explicitly for a multi-eventq simulation.
    sim_quantum = Param.Tick(0, "simulation quantum")

    full_system = Param.Bool("if this is a full system simulation")

    # Time syncing prevents the simulation from running faster than real time.
    time_sync_enable = Param.Bool(False, "whether time syncing is enabled")
    time_sync_period = Param.Clock("100ms", "how often to sync with real time")
    time_sync_spin_threshold = \
            Param.Clock("100us", "when less than this much time is left, spin")
```

The Root Python class utilize singleton design pattern that restricts the 
instantiation of a class to only one instance and provides a global point of 
access to that instance. The getInstance returns singleton object.

### Instantiate CPP implementation

```python
def instantiate(ckpt_dir=None):
    from m5 import options
    
    root = objects.Root.getInstance()
        
    if not root:
        fatal("Need to instantiate Root() before calling instantiate()")
    
    # we need to fix the global frequency
    ticks.fixGlobalFrequency()

    # Make sure SimObject-valued params are in the configuration
    # hierarchy so we catch them with future descendants() walks
    for obj in root.descendants(): obj.adoptOrphanParams()
    
    # Unproxy in sorted order for determinism
    for obj in root.descendants(): obj.unproxyParams()
    
    ......
    
    # Create the C++ sim objects and connect ports
    for obj in root.descendants(): obj.createCCObject()
    for obj in root.descendants(): obj.connectPorts()

    # Do a second pass to finish initializing the sim objects
    for obj in root.descendants(): obj.init()
    
    # Do a third pass to initialize statistics
    stats._bindStatHierarchy(root)
    root.regStats()
    ......
```

The main role of the instantiate function is iterating all SimObjects in the 
hierarchies and initialize CPP classes and ports. As we already set-up all 
required information to instantiate CPP classes (e.g., Params) and connectivity
between the hardware components (e.g., Ports), its role is invoking proper 
CPP functions to finalize set-up!

```python
    def descendants(self):
        yield self
        # The order of the dict is implementation dependent, so sort
        # it based on the key (name) to ensure the order is the same
        # on all hosts
        for (name, child) in sorted(self._children.items()):
            for obj in child.descendants():
                yield obj
```

One thing to note is because Root Python class is also SimObject, but the root
node in hierarchy, it can access other system components through 'descendants' 
method provided by the SimObject. It just iterates all SimObject!

### Create CPP objects!
```python
    # Call C++ to create C++ object corresponding to this object
    def createCCObject(self):
        self.getCCParams()
        self.getCCObject() # force creation
```

Our goal is instantiating CPP class object representing hardware component. Since
the information required for initializing this class is conveyed to the class 
constructor, so first of all it needs the Param struct. And then, we need to 
instantiate the CPP class representing the hardware component.

```python
    def getCCParams(self):
        if self._ccParams:
            return self._ccParams
        
        cc_params_struct = getattr(m5.internal.params, '%sParams' % self.type)
        cc_params = cc_params_struct()
        cc_params.name = str(self)
        
        param_names = list(self._params.keys())
        param_names.sort()
        for param in param_names:
            value = self._values.get(param)
            if value is None:
                fatal("%s.%s without default or user set value",
                      self.path(), param)
            
            value = value.getValue()
            if isinstance(self._params[param], VectorParamDesc):
                assert isinstance(value, list)
                vec = getattr(cc_params, param)
                assert not len(vec)
                # Some types are exposed as opaque types. They support
                # the append operation unlike the automatically
                # wrapped types.
                if isinstance(vec, list):
                    setattr(cc_params, param, list(value))
                else:
                    for v in value:
                        getattr(cc_params, param).append(v)
            else:
                setattr(cc_params, param, value)
        
        port_names = list(self._ports.keys())
        port_names.sort()
        for port_name in port_names:
            port = self._port_refs.get(port_name, None)
            if port != None: 
                port_count = len(port)
            else:
                port_count = 0 
            setattr(cc_params, 'port_' + port_name + '_connection_count',
                    port_count)
        self._ccParams = cc_params
        return self._ccParams
```

As we have all required information to generate and initialize Param struct, we 
should utilize it! First of all, we need to instantiate the Param struct associated
with the class that we want to instantiate to simulate one hardware component.
We've seen that the automatically generated pybind code exports the Param struct
to Python. 

```python
# gem5/src/Python/m5/internal/params.py

for name, module in inspect.getmembers(_m5):
    if name.startswith('param_') or name.startswith('enum_'):
        exec("from _m5.%s import *" % name)
```

As all CPP implementations are exported to Python as a module of '_m5' the 
Struct mapped for Param that we need to instantiate the CPP class should be 
accessible from importing '_m5' module. 

```cpp
static void
module_init(py::module &m_internal)
{
    py::module m = m_internal.def_submodule("param_BaseTLB");
    py::class_<BaseTLBParams, SimObjectParams, std::unique_ptr<BaseTLBParams, py::nodelete>>(m, "BaseTLBParams")
        .def_readwrite("port_cpu_side_ports_connection_count", &BaseTLBParams::port_cpu_side_ports_connection_count)
        .def_readwrite("port_mem_side_port_connection_count", &BaseTLBParams::port_mem_side_port_connection_count)
        ;

    py::class_<BaseTLB, SimObject, std::unique_ptr<BaseTLB, py::nodelete>>(m, "BaseTLB")
        ;

}
```
For example, BaseTLBParams CPP struct will be exported as '_m5.param_BaseTLB'.
Therefore all pybind exported CPP implementation will be imported to 
m5.internal.params module and 'cc_params_struct' will get the Python Class
object of the Param struct. By instantiating it, cc_params will have the instance
of the class, and will be initialized based on the values previously collected 
from the Python class BaseTLB. After initializing all fields of the struct, it 
assign the object to the '_ccParams'. 


```python
    def getCCObject(self):
        if not self._ccObject:
            # Make sure this object is in the configuration hierarchy
            if not self._parent and not isRoot(self):
                raise RuntimeError("Attempt to instantiate orphan node")
            # Cycles in the configuration hierarchy are not supported. This
            # will catch the resulting recursion and stop.
            self._ccObject = -1
            if not self.abstract:
                params = self.getCCParams()
                self._ccObject = params.create()
        elif self._ccObject == -1:
            raise RuntimeError("%s: Cycle found in configuration hierarchy." \
                  % self.path())
        return self._ccObject
```

Now as we have the Param struct object, we need to instantiate a CPP class 
object that actually simulate the hardware logic. 'getCCParams' returns the 
Param struct object previously assigned to '_ccParams'. Afterwards, it invokes
create() method defined in the Param struct. That would be weird to you because
you cannot find the create method in the automatically generated Param struct. 
However, when you look at the auto-generated pybind code, you can definitely 
find it exports the create function defined for Param struct. That's because 
the create method should be implemented manually by the developer beforehand in
cpp code. 

```cpp
// gem5/src/sim/system.cc 

System *
SystemParams::create()
{
    return new System(this);
}
```

Each create method for hardware component should instantiate the CPP class 
associated with the component. Also note that it passes **this** to the System 
constructor which is the SystemParams passing all information required to 
initialize the class! Finally you can retrieve CPP class object instantiated 
with Param configured based on Python script. 


### Connect Ports in CPP
As we've seen in previous Python code, we established all connectivity between
hardware components in Python, not in actual CPP simulation. It is time to 
transfer this connection implemented in Python to CPP implementations to 
establish actual connection between simulated hardware components. 

```python
class SimObject(object):  
    def connectPorts(self):
        # Sort the ports based on their attribute name to ensure the
        # order is the same on all hosts
        for (attr, portRef) in sorted(self._port_refs.items()):
            portRef.ccConnect()

class PortRef(object):
    def ccConnect(self):
        if self.ccConnected: # already done this
            return
        
        peer = self.peer
        if not self.peer: # nothing to connect to
            return
    
        port = self.simobj.getPort(self.name, self.index)
        peer_port = peer.simobj.getPort(peer.name, peer.index)
        port.bind(peer_port)
    
        self.ccConnected = True 
```
Since PortRef Python class have all information required to establish connection
between two components (two end ports, self and peer), the remaining task is 
invoking proper CPP functions to establish the connection as described by the 
Python PortRef. First of all, it needs information about two end-ports that 
should be connected to each other in CPP implementation. 

```python 
class SimObject(object): 
    @cxxMethod(return_value_policy="reference")
    def getPort(self, if_name, idx):
        pass

def cxxMethod(*args, **kwargs):
    """Decorator to export C++ functions to Python"""

    def decorate(func):
        name = func.__name__
        override = kwargs.get("override", False)
        cxx_name = kwargs.get("cxx_name", name)
        return_value_policy = kwargs.get("return_value_policy", None)
        static = kwargs.get("static", False)
        
        args, varargs, keywords, defaults = inspect.getargspec(func)
        if varargs or keywords:
            raise ValueError("Wrapped methods must not contain variable " \
                             "arguments")
    
        # Create tuples of (argument, default)
        if defaults:
            args = args[:-len(defaults)] + \
                   list(zip(args[-len(defaults):], defaults))
        # Don't include self in the argument list to PyBind
        args = args[1:]

    
        @wraps(func)
        def cxx_call(self, *args, **kwargs):
            ccobj = self.getCCClass() if static else self.getCCObject()
            return getattr(ccobj, name)(*args, **kwargs)
    
        @wraps(func)
        def py_call(self, *args, **kwargs):
            return func(self, *args, **kwargs)

        f = py_call if override else cxx_call
        f.__pybind = PyBindMethod(name, cxx_name=cxx_name, args=args,
                                  return_value_policy=return_value_policy,
                                  static=static)

        return f

    if len(args) == 0:
        return decorate
    elif len(args) == 1 and len(kwargs) == 0:
        return decorate(*args)
    else:
        raise TypeError("One argument and no kwargs, or only kwargs expected")
```

GEM5 defines decorator function cxxMethod which bridge the Python function call
to corresponding CPP function call. I will not cover details of decorator in 
Python. Please refer to this 
[blog posting for further details](https://realPython.com/primer-on-Python-decorators/).
The important thing is when you invoke getPort, it will invoke getPort member 
function defined in the CPP class representing hardware component having the 
port. Let's see the example.

```cpp
Port &
BaseXBar::getPort(const std::string &if_name, PortID idx)
{
    if (if_name == "mem_side_ports" && idx < memSidePorts.size()) {
        // the memory-side ports index translates directly to the vector
        // position
        return *memSidePorts[idx];
    } else  if (if_name == "default") {
        return *memSidePorts[defaultPortID];
    } else if (if_name == "cpu_side_ports" && idx < cpuSidePorts.size()) {
        // the CPU-side ports index translates directly to the vector position
        return *cpuSidePorts[idx];
    } else {
        return ClockedObject::getPort(if_name, idx);
    }
}
```

BaseXBar has three member fields describing hardware ports. Therefore, when the 
getPort is invoked from the Python class, for example SystemXBar inheriting the 
BaseXBar, it will invoke the getPort of the BaseXBar. Also, based on the passed
string, and index (for vectored ports), it will return CPP port member field of 
the class to Python! Since the returned object is CPP object not Python, the 
bind function will be invoked from CPP. 


```cpp
void
RequestPort::bind(Port &peer)
{
    auto *response_port = dynamic_cast<ResponsePort *>(&peer);
    fatal_if(!response_port, "Can't bind port %s to non-response port %s.",
             name(), peer.name());
    // request port keeps track of the response port
    _responsePort = response_port;
    Port::bind(peer);
    // response port also keeps track of request port
    _responsePort->responderBind(*this);
}
```

The actual binding is very simple operation because it just tracks the information
about the port and its connection (peer port). I will cover how the ports are 
utilized in simulation to transfer data between the components connected through 
the ports. In this posting, understanding how to establish the connection between
two different components having port would be sufficient. 

```cpp
class Port
{
    /** Attach to a peer port. */
    virtual void
    bind(Port &peer)
    {
        _peer = &peer;
        _connected = true;
    }

void
ResponsePort::responderBind(RequestPort& request_port)
{
    _requestPort = &request_port;
    Port::bind(request_port);
}
```

Binding should be done in bi-directional, so the above function establish the 
connection in two different ports (request and response). 


## Final remarks
At the first outlook, it must be very confusing to understand why GEM5 has 
Python script and CPP defining similar classes, which makes you misunderstand 
what is the role of each classes defined in different languages. However, the 
the points is the actual simulation is mostly achieved by CPP implementation, 
and the Python is a wrapper for those CPP implementation. In detail, the Python
is utilized to configure hardware parameters such as cache size, data size, and
whatnot. 
I covered several Python specific concepts such as metaclass and pybind to allow
GEM5 automatically generate several CPP implementations and its binding to Python
so that Python script can instantiate the CPP class object for actual simulation.
Hope that this posting can help you understand mysterious configuration of GEM5.






