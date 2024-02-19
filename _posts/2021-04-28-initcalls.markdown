---
layout: post
titile: "Initcalls: Initializing Linux subsystems"
categories: linux, embedded-linux
---

# do_initcalls
```c
static void __init do_basic_setup(void)
{
        cpuset_init_smp();
        driver_init();
        init_irq_proc();
        do_ctors();
        usermodehelper_enable();
        do_initcalls();
}
```
Now let's go back to previous setup function do_basic_setup.
Because rest of the init functions are not important in this posting,
so we will directly jump into do_initcalls function.


```c
static void __init do_initcalls(void)
{
        int level;
        size_t len = strlen(saved_command_line) + 1;
        char *command_line;

        command_line = kzalloc(len, GFP_KERNEL);
        if (!command_line)
                panic("%s: Failed to allocate %zu bytes\n", __func__, len);

        for (level = 0; level < ARRAY_SIZE(initcall_levels) - 1; level++) {
                /* Parser modifies command_line, restore it each time */
                strcpy(command_line, saved_command_line);
                do_initcall_level(level, command_line);
        }

        kfree(command_line);
}

static void __init do_initcall_level(int level, char *command_line)
{
        initcall_entry_t *fn;

        parse_args(initcall_level_names[level],
                   command_line, __start___param,
                   __stop___param - __start___param,
                   level, level,
                   NULL, ignore_unknown_bootoption);

        trace_initcall_level(initcall_level_names[level]);
        for (fn = initcall_levels[level]; fn < initcall_levels[level+1]; fn++)
                do_one_initcall(initcall_from_entry(fn));
}

/* Keep these in sync with initcalls in include/linux/init.h */
static const char *initcall_level_names[] __initdata = {
        "pure",
        "core",
        "postcore",
        "arch",
        "subsys",
        "fs",
        "device",
        "late",
};

typedef int (*initcall_t)(void);
int __init_or_module do_one_initcall(initcall_t fn)
{
        int count = preempt_count();
        char msgbuf[64];
        int ret;

        if (initcall_blacklisted(fn))
                return -EPERM;

        do_trace_initcall_start(fn);
        ret = fn();
        do_trace_initcall_finish(fn, ret);

        msgbuf[0] = 0;

        if (preempt_count() != count) {
                sprintf(msgbuf, "preemption imbalance ");
                preempt_count_set(count);
        }
        if (irqs_disabled()) {
                strlcat(msgbuf, "disabled interrupts ", sizeof(msgbuf));
                local_irq_enable();
        }
        WARN(msgbuf[0], "initcall %pS returned with %s\n", fn, msgbuf);

        add_latent_entropy();
        return ret;
}

```
For each predefined level, 
do_initcall invokes all the relevant init functions
for that level.
As shown in the initcall_level_names, 
there are 8 levels of init,
and do_initcall_level function is invoked per level. 
This function actually invokes all init functions
stored in a particular code section
dedicated for one level. 

The do_one_initcall function 
actually invokes the initcall functions one by one.
The type of function pointer of the initcalls 
are defined as initcall_t.
The function pointer is passed from the do_initcall_level function.
Each function pointer is retrieved as a result of 
initcall_from_entry function, and 
its parameter fn is retrieved
from the initcall_levels array.
Let's take a look at those structures and functions one by one.


```c
#ifdef CONFIG_HAVE_ARCH_PREL32_RELOCATIONS
typedef int initcall_entry_t;
        
static inline initcall_t initcall_from_entry(initcall_entry_t *entry)
{       
        return offset_to_ptr(entry);
}
#else
typedef initcall_t initcall_entry_t;

static inline initcall_t initcall_from_entry(initcall_entry_t *entry)
{       
        return *entry;
}
#endif  

extern initcall_entry_t __initcall_start[];
extern initcall_entry_t __initcall0_start[];
extern initcall_entry_t __initcall1_start[];
extern initcall_entry_t __initcall2_start[];
extern initcall_entry_t __initcall3_start[];
extern initcall_entry_t __initcall4_start[];
extern initcall_entry_t __initcall5_start[];
extern initcall_entry_t __initcall6_start[];
extern initcall_entry_t __initcall7_start[];
extern initcall_entry_t __initcall_end[];

static initcall_entry_t *initcall_levels[] __initdata = {
        __initcall0_start,
        __initcall1_start,
        __initcall2_start,
        __initcall3_start,
        __initcall4_start,
        __initcall5_start,
        __initcall6_start,
        __initcall7_start,
        __initcall_end,
};
```
initcall_levels array consists of multiple initcall_entry_t
which is a intger value 
imported from linux kernel header.


**include/asm-generic/vmlinux.lds.h**
```c
#define INIT_CALLS_LEVEL(level)                                         \
                __initcall##level##_start = .;                          \
                KEEP(*(.initcall##level##.init))                        \
                KEEP(*(.initcall##level##s.init))                       \

#define INIT_CALLS                                                      \
                __initcall_start = .;                                   \
                KEEP(*(.initcallearly.init))                            \
                INIT_CALLS_LEVEL(0)                                     \
                INIT_CALLS_LEVEL(1)                                     \
                INIT_CALLS_LEVEL(2)                                     \
                INIT_CALLS_LEVEL(3)                                     \
                INIT_CALLS_LEVEL(4)                                     \
                INIT_CALLS_LEVEL(5)                                     \
                INIT_CALLS_LEVEL(rootfs)                                \
                INIT_CALLS_LEVEL(6)                                     \
                INIT_CALLS_LEVEL(7)                                     \
                __initcall_end = .;

#define INIT_DATA_SECTION(initsetup_align)                              \
        .init.data : AT(ADDR(.init.data) - LOAD_OFFSET) {               \
                INIT_DATA                                               \
                INIT_SETUP(initsetup_align)                             \
                INIT_CALLS                                              \
                CON_INITCALL                                            \
                INIT_RAM_FS                                             \
        }
```
Linux kernel linker script defines 
INIT_CALLS_LEVEL macro that defines variable
that contains the starting address of 
memory region that have 
all initcall of specific level.
It also provides INIT_CALLS macro
that populates all the memory addresses 
used by the initcall_level array.
We can find that each __initcall_##level##_start is followed by the 
.initcall##level##.init and 
.initcall##level##s.init 
section.
Because level is a integer from 0 to 7
the section name should be 
from
.initcall0.init
to 
.initcall7.init
Let's try to figure out where those sections are defined,
and what content are stored in that section. 


**include/linux/init.h**
```c
/*
 * initcalls are now grouped by functionality into separate
 * subsections. Ordering inside the subsections is determined
 * by link order.
 * For backwards compatibility, initcall() puts the call in
 * the device init subsection.
 *
 * The `id' arg to __define_initcall() is needed so that multiple initcalls
 * can point at the same handler without causing duplicate-symbol build errors.
 *
 * Initcalls are run by placing pointers in initcall sections that the
 * kernel iterates at runtime. The linker can do dead code / data elimination
 * and remove that completely, so the initcall sections have to be marked
 * as KEEP() in the linker script.
 */

#ifdef CONFIG_HAVE_ARCH_PREL32_RELOCATIONS
#define ___define_initcall(fn, id, __sec)                       \
        __ADDRESSABLE(fn)                                       \
        asm(".section   \"" #__sec ".init\", \"a\"      \n"     \
        "__initcall_" #fn #id ":                        \n"     \
            ".long      " #fn " - .                     \n"     \
            ".previous                                  \n");
#else
#define ___define_initcall(fn, id, __sec) \
        static initcall_t __initcall_##fn##id __used \
                __attribute__((__section__(#__sec ".init"))) = fn;
#endif

#define __define_initcall(fn, id) ___define_initcall(fn, id, .initcall##id)

#define pure_initcall(fn)               __define_initcall(fn, 0)

#define core_initcall(fn)               __define_initcall(fn, 1)
#define core_initcall_sync(fn)          __define_initcall(fn, 1s)
#define postcore_initcall(fn)           __define_initcall(fn, 2)
#define postcore_initcall_sync(fn)      __define_initcall(fn, 2s)
#define arch_initcall(fn)               __define_initcall(fn, 3)
#define arch_initcall_sync(fn)          __define_initcall(fn, 3s)
#define subsys_initcall(fn)             __define_initcall(fn, 4)
#define subsys_initcall_sync(fn)        __define_initcall(fn, 4s)
#define fs_initcall(fn)                 __define_initcall(fn, 5)
#define fs_initcall_sync(fn)            __define_initcall(fn, 5s)
#define rootfs_initcall(fn)             __define_initcall(fn, rootfs)
#define device_initcall(fn)             __define_initcall(fn, 6)
#define device_initcall_sync(fn)        __define_initcall(fn, 6s)
#define late_initcall(fn)               __define_initcall(fn, 7)
#define late_initcall_sync(fn)          __define_initcall(fn, 7s)
```

Following the above macros,
it is easy to understand 
how the .initcallX.init section is generated, 
and each function is located in that section.

