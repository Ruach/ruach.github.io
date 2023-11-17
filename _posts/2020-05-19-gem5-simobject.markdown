---
layout: post
titile: "GEM5, from entry point to simulation loop"
categories: Gem5, SimObject, pybind11, metaclass
---

When you first take a look at the GEM5 source code, it could be confusing 
because it has python, CPP, and isa files which you might haven't seen before. 
In GEM5, Most of the simulation logic is implemented as a CPP, but it utilizes
python heavily for platform configuration and generate CPP class from templates.
Forget about isa file in this posting! I will go over it in another blog posting. 

Since the GEM5 execution is a mixture of CPP functions and python 
scripts, and there are duplicated names for classes and functions in both files,
it would be very to understand how GEM5 works. This confusion even start from 
the program execution. let's see the gem5 execution command, particularly for 
simulating X86 architecture. 

> build/X86/gem5.opt \<python script for configuration>

The gem5.opt is a **elf binary** compiled from GEM5 CPP code base. However, to 
run simulation, GEM5 requires additional configuration script written in python. 
This script specifies configuration of the platform you want to simulate with 
GEM5, which includes configuration of CPU, Memory, caches and buses. Wait, I 
told you most of the simulation logic is implemented as CPP, then why suddenly
python script is necessary for configuring simulated platform? 

I couldn't find any documents explaining about mixing python and CPP to implement 
GEM5, my guess is to decouple configuration part from the main code base to avoid 
re-compilation cost. If the user doesn't introduce new component nor want to 
simulate another architecture, changing configuration of the simulated platform 
would not need another compilation. 

Regardless of the reason, as GEM5 make heavy use of Python and CPP at the same
time, code execution would go back and forth between CPP and python. Also, as 
the name of the class and its attributes are identical or very similar in python
and CPP, it would be very confusing to follow the code base. Therefore, please 
be aware which part of the code it is when you go over this posting. 

### Pybind 11: Allowing python to access CPP definitions
As python and CPP both needs to access classes and attributes implemented in 
different language, it must need wrapper/helper. To allow python script to access
CPP defined classes and struct, GEM5 make heavy use of pybind11. 
I will not go over details of pybind11 in this posting, so please refer to 
[pybind11](https://pybind11.readthedocs.io/en/stable/basics.html), before 
continuing the read. 

Let's take a look at how GEM5 code base (implemented in CPP) exports its code 
and data to python. When you run gem5.opt binary, it will first invoke main 
function defined in CPP. GEM5 defines EmbeddedPython class to provide all 
functions and attributes for developer to export CPP code and data to python
through the pybind11.


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

    // Initialize the embedded m5 python library
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


As depicted in the above code,  **EmbeddedPython::initAll** will expose CPP 
definitions necessary to run simulation as python module so that python script 
can utilize CPP implementation. After export, it executes m5Main function to
transfer control to Python from the executable. Let's first see how GEM5 bind 
CPP classes to python through EmbeddedPython class.


#### Pybind Initialization (export CPP as python module)
Pybind11 allows python script to access CPP implementation through the format 
of python module. Therefore, after CPP exports through pybind11, python script 
can access CPP implementation by exporting python module easily. 

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

The above function exports CPP definition as '_m5' module and its sub-module 
such as core, debug, event, and stats. Therefore, if python script wants to 
access debug related CPP implementation, then it can export '_m5.debug' module.
The initial few function invocations named as 'pybind_init_xx' exports basic 
functions and classes necessary for simulation. 

However, it doesn't exports CPP implementations related with actual hardware 
component simulation. In GEM5, it implements CPP classes to represent hardware 
components. Therefore to configure the platform through python script, it should 
be able to access CPP implementations associated with each hardware component.

The reason why I am talking about it separately from binding other CPP classes 
is that GEM5 automatically generates struct used a parameter to instantiate 
CPP class object. I bet it is unclear what parameter struct I am talking about,
you will see what it is soon! Please bare with me! Since those structs are 
generated automatically, bindings are handled by different functions in the 
above main function. 'getMap' function returns 

```cpp
std::map<std::string, EmbeddedPyBind *> &
EmbeddedPyBind::getMap()
{   
    static std::map<std::string, EmbeddedPyBind *> objs;
    return objs;
}
```

EmbeddedPyBind class defines map 'objs' and return this map. The main function
iterates this map and invokes 'init' function of the EmbeddedPyBind object. To 
call init function object should have been registered to the map beforehand. 

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

This registration is done by constructor of the EmbeddedPyBind class. However, 
you will not be able to find any relevant code instantiating EmbeddedPyBind for 
system component class. The reason is GEM5 automatically generate CPP code 
snippet and EmbeddedPyBind will be instantiated by that code. I will cover the 
details soon! Let's assume that all required CPP implementations were exported
to python through pybind11. 



#### Transferring execution control to python
After exporting CPP implementation, now it can finally jumps to GEM5 python 
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
    // bunch of python statements.
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
To transfer execution control to python code, it invokes 
[PyRun_String](https://docs.python.org/3/c-api/veryhigh.html)
PyRun_String is a function in the Python C API that allows you to execute a 
Python code snippet from a C program. It takes a string containing the Python 
code as one of its arguments and executes it within the Python interpreter.
As depicted in the above CPP string, m5MainCommands, it will invoks m5.main 
through PyRun_String. 

### GEM5 m5 main python code
> From this part, the execution is transferred to python snippet.


```python
//src/python/m5/main.py 

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

There are two important initialization code in the above python code: 
initializing main event queue and execute python snippet originally provided 
to gem5.opt. The event queue will be covered in [another blog posting][]. 
You might remember that we have passed config script defining configuration 
of one platform we want to simulate. That python script is passed to above 
python code snippet through 'sys.argv[0]', and compiled and exec. 
Therefore, it will not return to CPP, but the execution control is transferred
to configuration python script!


### How GEM5 nicely orchestrates python script and CPP implementation?
#### Python platform configuration script
To understand how python configuration script interacts with CPP implementation 
in simulating one architecture, I will pick very simple configuration script 
provided by GEM5. Note that it is not complete version of the script. 

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

In the above python configuration script, it instantiates CPU, crossbar, and 
DRAM. Also, it connects the CPU to memory through the crossbar. I mentioned that
GEM5 implements each hardware component as CPP class to simulate it. Then, does
the above python script instantiates CPP class? or another python class objects?
For example, GEM5 implements System class in CPP and python both. The answer is 
python class! I will cover how this python classes used in the script will be 
transformed into actual CPP classes. Furthermore, I will tell you how these 
hardware components can be connected each other to provide full system emulation. 

#### Python class as a wrapper for instantiating CPP
We don't know how python class will instantiate CPP class objects, but when we 
look at the implementation of constructor function of the CPP and attributes 
of python class, we can reason guess python class is relevant with the parameter
required for instantiating the CPP class object. Let's see!

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

For example, cache_line_size is a attribute of the python class, and also it is
used to initialize same name member filed of System CPP class. The automatically
generated CPP struct previously mentioned in this posting is for generating 
Param class that will be passed to CPP class to instantiate it. We don't know 
how this class is automatically generated and used to instantiate CPP class 
object from python script yet, I will cover the details one by one. 

### Generating Param class
Let's see what CPP code will be automatically generated from the python class 
to help us get the big picture. 

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
SystemParams struct is automatically generated. Note that it  will be used as 
parameter for instantiating System CPP class representing system component. 

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

Also, the automatically generated struct should be accessible from the python
so that it can generate required parameter from the python class. 

#### SimObject python class
To understand how GEM5 automatically generate CPP param class and its pybind 
from python classes, we should understand SimObject class and MetaSimObject 
metaclass. In gem5, a SimObject represents a simulation entity and forms the 
basis for modeling components within the system being simulated. In other words, 
all system component related classes instantiated in the python configuration 
script should be inherited from the SimObject class. 

```python
# gem5/src/python/m5/SimbObject.py

@add_metaclass(MetaSimObject)
class SimObject(object):
    # Specify metaclass.  Any class inheriting from SimObject will
    # get this metaclass.
    type = 'SimObject'
    abstract = True
```

Although SimObject is the fundamental building block of GEM5 simulation in 
defining hardware components, its metaclass, MetaSibObject is the most important
in terms of bridging python to CPP. 

#### MetaSimObject: metaclass of SimObject 
When one python class has metaclass, functions defined in metaclass can 
pre-process newly defined class. For example, attributes of python class having 
metaclass can be audited by metaclasss functions such as '__init__, __new__ or, 
__call__'. Since metaclass can access class and its attributes (dictionary), it 
can modify or introduce particular attribute and logic during the class 
instantiation. For further details of metaclass, please refer to 
[python-metaclass](https://realpython.com/python-metaclasses/).


```python
#src/python/m5/SimObject.py

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

Also, remind that actual system components simulating architecture is 
implemented C++ code not python code. I will say python classes are interface 
or wrapper for actual implementation of simulation logic in C++. Therefore, 
each python system components should be able to access C++ functions matching 
python classes. 

#### Generate CPP Param struct and its pybind {#cpp-auto}
When you look at the python class for System, you can find that there are some 
python attributes not related with the CPP System class. We only need to filter
out python class attributes that is necessary for communication with CPP class
counterpart. If it reminds you of python metaclass, you don't need to study 
more about python metaclass. As I told you, because python metaclass allows it 
to access all attributes of class having it as metaclass, so it would be a nice
place to **filter out only necessary attributes!**

Before we take a look at how metaclass helps us filter out only interesting 
attributes from the python class, let's take a look at the python code that 
automatically generates Param struct to get idea about which attributes of the 
python classes should be filtered out to generate CPP code. 
As most of the python based automatic code generation utilize python string and
substitution, you can easily find the function by searching some of the generated 
code logic in CPP.

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

When you compare above code with the automatically generated struct, then you 
can easily figure out which parts of the python code generate which parts of the
CPP implementation. Below is the python code for generating CPP function to 
export automatically generated struct to python through pybind. 


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
#include "python/pybind11/core.hh"
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

``` python
class PyBindProperty(PyBindExport):
    def __init__(self, name, cxx_name=None, writable=True):
        self.name = name
        self.cxx_name = cxx_name if cxx_name else name
        self.writable = writable
        
    def export(self, code, cname):
        export = "def_readwrite" if self.writable else "def_readonly"
        code('.${export}("${{self.name}}", &${cname}::${{self.cxx_name}})')
```

When you carefully compare the automatically generated code and python code side
by side, you can figure out that port and param related python attributes are 
important in both generating CPP implementation of Param struct and its pybind.


##### __init__ of MetaSimObject
Let's see how metaclass help us filter out param and port related attribute 
from python classes inheriting SimObject. 

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

Thanks to metaclass, the above __init__ function of the MetaSimObject meta class
will be invoked for any python classes inheriting SimObject because SimObject 
set MetaSimObject as its metaclass. It iterates all attributes in the class and 
check if it is either **ParamDesc or Port** instance. Based on which instance 
it is, it will invoke '_new_param' or 'new_port' which put the attribute in 
'_params' and '_ports' dictionary of the class (i.e., filtering out two 
attributes in the dictionary).

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

When you take a look at the [code](cpp-auto) once again, you can understand how
these two newly introduced dictionaries are used as a key for automatically 
generating CPP implementation for Param struct and its pybind code. One last note
is it is developer's role to define python class attributes corresponding to 
CPP implementation so that Param struct and pybind method can be automatically
generated to connect CPP implementation to python.

```cpp
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
```

For example to connect python attribute mem_mode to Enums::MemoryMode mem_mode
filed of the CPP implementation, developer should define python attributes 
properly with Param class. 

#### Collected Params to CPP variable. 
Python Param class is a placeholder for any parameter that should be translated 
into CPP from python attribute. Compared with python which doesn't need a strict
type for attribute, CPP need clear and distinct type for all variables. Therefore,
to translate python attribute to CPP variable, GEM5 should manage value and type
altogether, which is done by ParamDesc class. 

```python
# python/m5/params.py

class ParamDesc(object):
    def cxx_decl(self, code):
        code('${{self.ptype.cxx_type}} ${{self.name}};')
```

The 'cxx_decl' method is invoked when GEM5 automatically translate python 
attributes (instance of ParamDesc) to CPP variable. You might wonder why it is
ParamDesc not Param previously used to define attributes in python class.

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

For example let's assume you have below python attribute.

```python
    cache_line_size = Param.Unsigned(64, "Cache line size in bytes")
```

Although there is no Unsigned attribute in Param, it will invoke '__getattr__'
function of the ParamFactory with 'Unsigned'. It will create a new instance of 
ParamFactory, and it will be used to invoke function with following parameters
in the parentheses. As it is treated as function call, it will further invoke
'__call__' function of the ParamFactory. After retrieving the type from allParams
dictionary mapped to ptype_str which will be Unsigned in this case. Therefore,
allParams dictionary should be generated before the ParamFactory is utilized. 

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
To add allParams dictionary, GEM5 utilize another python metaclass.

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
When Unsigned class is initialized, it will invoke MetaParamValue metaclass 
and generate mapping from Unsigned to class object of Unsigned(CheckedInt). 
Therefore, when it encounters Param.Unsigned, it will return Unsigned(CheckedInt)
class. I will stop here because it will be too complicated when I go over 
metaclasses and its functions further. If you want to understand how this 
returned class object is used to instantiate proper object, recommend you to 
take a look at more details of metaclasses of CheckedInt.

#### XXX
```python
class System(SimObject):
    ......
    mem_mode = Param.MemoryMode('atomic', "The mode the memory system is in")
    ......
```
However, when you take a look at the python classes, it doesn't utilize pybind 
directly to access CPP objects. All python attributes related with Params are 
accessed as if it is vanilla python attributes. However, what we want is the 
access to attributes relevant with Param is translated into CPP object accesses
through the pybind!

```python
    # Get C++ object corresponding to this object, calling C++ if
    # necessary to construct it.  Does *not* recursively create
    # children.
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

#### Sconscript: generating files for CPP implementation 
Now we can understand where the python code is located and how the data required
for generating CPP implementation can be gathered from each python class. Then,
some program should invoke the python method to generate actual CPP and header
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
        cc_file = File('python/_m5/param_%s.cc' % name)
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
there are two locations invoking python methods that you must be familiar with
(obj.pybind_decl and obj.cxx_param_decl). One thing not clear in the SConscript 
is **sim_objects**. 

```python
# gem5/src/SConscript  

sim_objects = m5.SimObject.allClasses
```

In the SConscript, it is defined as attribute from m5.SibObject python module. 
Then what is allClasses? The answer is in the MetaSimObject!

```python
# python/m5/SimObject.py

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
python classes inheriting from SimObject and fill out allClasses dictionary,
all python classes should be imported first. 


```python
class SimObject(PySource):
    '''Add a SimObject python file as a python source object and add
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

To import relevant python classes, root SConscript defines SimObject class and 
import the classes to the python environment where SConscript is being executed. 

> Note that SimObject class is not identical to SimObject class having
> MetaSimObject as its metaclass used for defining simulated components. 

Then who instantiates above SimObjects? SConscript can exist in subdirectories 
to handle the build details. Let's take a look at the sub-directory containing 
python code defining python classes inheriting SimObject. 


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

As shown in the above script, it instantiates SimObject to import python classes
defining hardware simulation building block. You might wonder how this exported 
CPP implementation can be utilized by python classes, but please bear with me!
I will give you details after covering Port!


### Port
While going through Params and its pybind, you may have noticed that 
MetaSimObject filter out Port attributes from python classes separately as well
as the ParamDesc instance. Since GEM5 is a full system simulator, it requires
not only various hardware components such as CPU and memory controller 
consisting of the platform, but also the wires connecting these hardware. To 
enable communication between different hardware components, GEM5 introduce 
port concept and embed it in each python class representing any hardware 
components. 


#### Python port to represent component relationship
The Port classes are utilized to represent connection between hardware components.
However, since all simulation logic is implemented in CPP not in python, the
connectivity presented in python code should be transformed into CPP and generate
connection between CPP class objects representing hardware components. Therefore,
we need to understand how this transformation happens.

```python
class System(SimObject):                                                        
    type = 'System'                                                             
    cxx_header = "sim/system.hh"                                                
    system_port = RequestPort("System port")   
```

To define attributes related with port, GEM5 has python class Port and others 
inheriting the Port. 

```python
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

Let's see how python script generates connection between two different hardware
components through the port. 


```python
# create the system we are going to simulate
system = System()

# Create a memory bus, a system crossbar, in this case
system.membus = SystemXBar()

# Connect the system up to the membus
system.system_port = system.membus.slave
```

In the above code, it just assigns slave attribute of memory bus to system_port
attribute of the system. Although it can be seen as just normal assignment, 
there is a complicated details behind to support the assignment of the Port. 
To understand it, please remind that all hardware component classes inherits
SimObject. SimObject class defines __getattr__ and __setattr__ functions to 
assist special attribute access and assignment. Let's see one by one in detail.


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

To understand the reference of system.membus.slave, we have to understand how 
membus could have been assigned as a attribute of system. Since there is no 
statically defined attribute called membus in system, it is added to system 
class object at runtime. Since SimObject defines __setattr__ function, it will 
be invoked when new attribute is added to the object. As the value added to the 
object is another SimObject class object retrieved from SystemXBar(), it will be
handled as child of the system. 

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

Remind that I mentioned that SimObject can be hierarchically organized. As the 
System is a class representing entire simulated system, logically the crossbar
connecting hardware components in the system should be child of the system. 
Now let's see what happens if it tries to access system.membus.slave!

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

The access can be achieved through two __getattr__ method call. Note that it 
can be treated as '(system.membus).slave'. Because System is SimObject, and as
SimObject class defines __getattr__ function, this function will be automatically 
invoked to access membus attribute. As membus has been registered as child of the 
system, SystemXBar class object will be retrieved first. Also, as it is SimObject,
when slave attribute is accessed, it will invoke another __getattr__ function.
Because slave attribute is declared as Port in BaseXBar class which is the base
python class of SystemXBar, it should have been filtered out as '_ports' when the 
SystemXBar is defined, thanks to metaclass. When the attribute is related with 
Port, then it will invoke '_get_port_ref' to return reference of that port

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

SimObject has cache for reference of Port, self_port_refs. If it is the first
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

You can find that it generates instance of PortRef. Port is a wrapper class 
for conveying information about the port and actual reference to the Port 
is defined by the PortRef class. Also retrieved PortRef instance will be stored
in the '_ports' attribute of the SimObject. This will be utilized later to 
transfer python presented connectivity between the hardware components to CPP! 
Anyway the RHS of the assignment is transformed into object of PortRef!


To assign it to 'system.system_port' (LHS) it will invoke another '__setattr__'
of the SimObject!

```python
        if attr in self._ports:                                                 
            # set up port connection                                            
            self._get_port_ref(attr).connect(value)                             
            return                     
```

At this time, because the 'system_port' is declared as Port class, this attribute
must exist in the '_ports' dictionary. When you think about assignment in terms
of port logically, it should connect two hardware components. To achieve it, it 
actually invokes 'connect' function! As the '_get_port_ref' returns another 
PortRef of the system_port, it will connect PortRef of system_port and slave. 


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

### Python to CPP transformation 
Whoa! it was quite intense cause GEM5 make heavy use of python classes to 
present and organize hardware components. However, the most important question 
has not been answered yet! Since the python is just a wrapper for CPP classes
used in actual simulation, the configuration specified as python should be 
translated into CPP implementation including CPP class instantiating and 
connection between them. 

```python
# set up the root SimObject and start the simulation
root = Root(full_system = False, system = system)
# instantiate all of the objects we've created above
m5.instantiate()
```

When you finish configuration, you should instantiate Root class and invoke 
instantiate function to transform your python configurations into CPP implementation.


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

The Root python class utilize singleton design pattern that restricts the 
instantiation of a class to only one instance and provides a global point of 
access to that instance. The getInstance returns singleton object.

#### Time to instantiate CPP implementation

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

One thing to note is because Root python class is also SimObject, but the root
node in hierarchy, it can access other system components through 'descendants' 
method provided by the SimObject. It just iterates all SimObject!

#### Create CPP objects!
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
to python. 

```python
# gem5/src/python/m5/internal/params.py

for name, module in inspect.getmembers(_m5):
    if name.startswith('param_') or name.startswith('enum_'):
        exec("from _m5.%s import *" % name)
```

As all CPP implementations are exported to python as a module of '_m5' the 
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
m5.internal.params module and 'cc_params_struct' will get the python Class
object of the Param struct. By instantiating it, cc_params will have the instance
of the class, and will be initialized based on the values previously collected 
from the python class BaseTLB. After initializing all fields of the struct, it 
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
with Param configured based on python script. 


#### Connect Ports in CPP
As we've seen in previous python code, we established all connectivity between
hardware components in python, not in actual CPP simulation. It is time to 
transfer this connection implemented in python to CPP implementations to 
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
Since PortRef python class have all information required to establish connection
between two components (two end ports, self and peer), the remaining task is 
invoking proper CPP functions to establish the connection as described by the 
python PortRef. First of all, it needs information about two end-ports that 
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

GEM5 defines decorator function cxxMethod which bridge the python function call
to corresponding CPP function call. I will not cover details of decorator in 
python. Please refer to this 
[blog posting for further details](https://realpython.com/primer-on-python-decorators/).
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
getPort is invoked from the python class, for example SystemXBar inheriting the 
BaseXBar, it will invoke the getPort of the BaseXBar. Also, based on the passed
string, and index (for vectored ports), it will return CPP port member field of 
the class to python! Since the returned object is CPP object not python, the 
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


### Final remarks
At the first outlook, it must be very confusing to understand why GEM5 has 
python script and CPP defining similar classes, which makes you misunderstand 
what is the role of each classes defined in different languages. However, the 
the points is the actual simulation is mostly achieved by CPP implementation, 
and the python is a wrapper for those CPP implementation. In detail, the python
is utilized to configure hardware parameters such as cache size, data size, and
whatnot. 
I covered several python specific concepts such as metaclass and pybind to allow
GEM5 automatically generate several CPP implementations and its binding to python
so that python script can instantiate the CPP class object for actual simulation.
Hope that this posting can help you understand mysterious configuration of GEM5.






