---
layout: post
titile: "Linux usb core driver interface, part1"
categories: linux, embedded-linux
---

# Initializing usb subsystem 
```c
/*
 * Init
 */
static int __init usb_init(void)
{
        int retval;
        if (usb_disabled()) {
                pr_info("%s: USB support disabled\n", usbcore_name);
                return 0;
        }
        usb_init_pool_max();

        usb_debugfs_init();

        usb_acpi_register();
        retval = bus_register(&usb_bus_type);
        if (retval)
                goto bus_register_failed;
        retval = bus_register_notifier(&usb_bus_type, &usb_bus_nb);
        if (retval)
                goto bus_notifier_failed;
        retval = usb_major_init();
        if (retval)
                goto major_init_failed;
        retval = usb_register(&usbfs_driver);
        if (retval)
                goto driver_register_failed;
        retval = usb_devio_init();
        if (retval)
                goto usb_devio_init_failed;
        retval = usb_hub_init();
        if (retval)
                goto hub_init_failed;
        retval = usb_register_device_driver(&usb_generic_driver, THIS_MODULE);
        if (!retval)
                goto out;

        usb_hub_cleanup();
hub_init_failed:
        usb_devio_cleanup();
usb_devio_init_failed:
        usb_deregister(&usbfs_driver);
driver_register_failed:
        usb_major_cleanup();
major_init_failed:
        bus_unregister_notifier(&usb_bus_type, &usb_bus_nb);
bus_notifier_failed:
        bus_unregister(&usb_bus_type);
bus_register_failed:
        usb_acpi_unregister();
        usb_debugfs_cleanup();
out:
        return retval;
}

#define subsys_initcall(fn)             __define_initcall(fn, 4)
subsys_initcall(usb_init);
```

### Usb bus registration
Based on the previous postings,
we can know that a bus_type object 
representing a specific bus sub-system
should be initialized and registered
by invoking bus_register function. 
Let's take a look at which field of bus_type 
has been statically provided by the usb core first.

```c
struct bus_type usb_bus_type = {
        .name =         "usb",
        .match =        usb_device_match,
        .uevent =       usb_uevent,
        .need_parent_lock =     true,
};
```
Compared to the bus_type object used for the platform bus,
usb bus_type object provides only handful of information.
Note that even the probe function has not been provided. 

### Registering notifier block for usb bus
We doesn't utilize the notifier block for the platform bus, 
but usb bus utilize the notifier block.
The bus_register_notifier set the usb_bus_nb notifier block 
to the initialized usb bus.

```c
static struct notifier_block usb_bus_nb = {
        .notifier_call = usb_bus_notify,
};   

/*
 * Notifications of device and interface registration
 */
static int usb_bus_notify(struct notifier_block *nb, unsigned long action,
                void *data)
{
        struct device *dev = data;

        switch (action) {
        case BUS_NOTIFY_ADD_DEVICE:
                if (dev->type == &usb_device_type)
                        (void) usb_create_sysfs_dev_files(to_usb_device(dev));
                else if (dev->type == &usb_if_device_type)
                        usb_create_sysfs_intf_files(to_usb_interface(dev));
                break;

        case BUS_NOTIFY_DEL_DEVICE:
                if (dev->type == &usb_device_type)
                        usb_remove_sysfs_dev_files(to_usb_device(dev));
                else if (dev->type == &usb_if_device_type)
                        usb_remove_sysfs_intf_files(to_usb_interface(dev));
                break;
        }
        return 0;
}  
```
When the notification is sent, the above usb_bus_notify function will be invoked 
with the action parameter.
Based on the action, 
it hanldes usb device management on the sysfs.

### Register usb filesystem driver, usbfs

```c
struct usb_driver usbfs_driver = {
        .name =         "usbfs",
        .probe =        driver_probe,
        .disconnect =   driver_disconnect,
        .suspend =      driver_suspend,
        .resume =       driver_resume,
        .supports_autosuspend = 1,
};      

#define usb_register(driver) \
        usb_register_driver(driver, THIS_MODULE, KBUILD_MODNAME)

/**
 * usb_register_driver - register a USB interface driver
 * @new_driver: USB operations for the interface driver
 * @owner: module owner of this driver.
 * @mod_name: module name string
 *
 * Registers a USB interface driver with the USB core.  The list of
 * unattached interfaces will be rescanned whenever a new driver is
 * added, allowing the new driver to attach to any recognized interfaces.
 *
 * Return: A negative error code on failure and 0 on success.
 *
 * NOTE: if you want your driver to use the USB major number, you must call
 * usb_register_dev() to enable that functionality.  This function no longer
 * takes care of that.
 */
int usb_register_driver(struct usb_driver *new_driver, struct module *owner,
                        const char *mod_name)
{       
        int retval = 0;
        
        if (usb_disabled())
                return -ENODEV;

        new_driver->drvwrap.for_devices = 0;
        new_driver->drvwrap.driver.name = new_driver->name;
        new_driver->drvwrap.driver.bus = &usb_bus_type;
        new_driver->drvwrap.driver.probe = usb_probe_interface;
        new_driver->drvwrap.driver.remove = usb_unbind_interface;
        new_driver->drvwrap.driver.owner = owner;
        new_driver->drvwrap.driver.mod_name = mod_name;
        new_driver->drvwrap.driver.dev_groups = new_driver->dev_groups;
        spin_lock_init(&new_driver->dynids.lock);
        INIT_LIST_HEAD(&new_driver->dynids.list);
 
        retval = driver_register(&new_driver->drvwrap.driver);
        if (retval)
                goto out; 
 
        retval = usb_create_newid_files(new_driver);
        if (retval)
                goto out_newid;
        
        pr_info("%s: registered new interface driver %s\n",
                        usbcore_name, new_driver->name);
        
out:    
        return retval;

out_newid:
        driver_unregister(&new_driver->drvwrap.driver);
 
        pr_err("%s: error %d registering interface driver %s\n",
                usbcore_name, retval, new_driver->name);
        goto out;
}
```

usb_register macro invokes usb_register_driver 
which register the usb related driver to the usb bus.


### Initializing usb devio
```c
static struct cdev usb_device_cdev;
        
int __init usb_devio_init(void)
{               
        int retval;
        
        retval = register_chrdev_region(USB_DEVICE_DEV, USB_DEVICE_MAX,
                                        "usb_device");
        if (retval) {
                printk(KERN_ERR "Unable to register minors for usb_device\n");
                goto out;
        }
        cdev_init(&usb_device_cdev, &usbdev_file_operations);
        retval = cdev_add(&usb_device_cdev, USB_DEVICE_DEV, USB_DEVICE_MAX);
        if (retval) {
                printk(KERN_ERR "Unable to get usb_device major %d\n",
                       USB_DEVICE_MAJOR);
                goto error_cdev;
        }
        usb_register_notify(&usbdev_nb);
out:    
        return retval;

error_cdev:
        unregister_chrdev_region(USB_DEVICE_DEV, USB_DEVICE_MAX);
        goto out;
}

const struct file_operations usbdev_file_operations = {
        .owner =          THIS_MODULE,
        .llseek =         no_seek_end_llseek,
        .read =           usbdev_read,
        .poll =           usbdev_poll,
        .unlocked_ioctl = usbdev_ioctl,
        .compat_ioctl =   compat_ptr_ioctl,
        .mmap =           usbdev_mmap,
        .open =           usbdev_open,
        .release =        usbdev_release,      
};


static int usbdev_notify(struct notifier_block *self,
                               unsigned long action, void *dev)
{               
        switch (action) {
        case USB_DEVICE_ADD:
                break;
        case USB_DEVICE_REMOVE:
                usbdev_remove(dev);
                break;
        }
        return NOTIFY_OK;
}               
        
static struct notifier_block usbdev_nb = {
        .notifier_call =        usbdev_notify,
};      

```
The first thing done by the usb devio initialization is 
initializing and creating the character device for usb devices.
Compared to platform devices,
usb devices provides interfaces to the user programs
so that the user can directly communicate with the 
device files of the usb devices. 
The usb_dev_file_operations provides 
file operations related callback functions for that purpose. 
XXX: how the other devices are accessed ? does it through the devio??????

### Registering usb hub device driver
```c
int usb_hub_init(void)
{       
        if (usb_register(&hub_driver) < 0) {
                printk(KERN_ERR "%s: can't register hub driver\n",
                        usbcore_name);
                return -1;
        }
        
        /*      
         * The workqueue needs to be freezable to avoid interfering with
         * USB-PERSIST port handover. Otherwise it might see that a full-speed
         * device was gone before the EHCI controller had handed its port
         * over to the companion full-speed controller.
         */
        hub_wq = alloc_workqueue("usb_hub_wq", WQ_FREEZABLE, 0);
        if (hub_wq)
                return 0;

        /* Fall through if kernel_thread failed */
        usb_deregister(&hub_driver);
        pr_err("%s: can't allocate workqueue for usb hub\n", usbcore_name);

        return -1;
}  
        
MODULE_DEVICE_TABLE(usb, hub_id_table);
static struct usb_driver hub_driver = {
        .name =         "hub",
        .probe =        hub_probe,
        .disconnect =   hub_disconnect,
        .suspend =      hub_suspend,
        .resume =       hub_resume,
        .reset_resume = hub_reset_resume,
        .pre_reset =    hub_pre_reset,
        .post_reset =   hub_post_reset,
        .unlocked_ioctl = hub_ioctl,
        .id_table =     hub_id_table,
        .supports_autosuspend = 1,
};      
                
static const struct usb_device_id hub_id_table[] = {
    { .match_flags = USB_DEVICE_ID_MATCH_VENDOR
                   | USB_DEVICE_ID_MATCH_PRODUCT
                   | USB_DEVICE_ID_MATCH_INT_CLASS,
      .idVendor = USB_VENDOR_SMSC,
      .idProduct = USB_PRODUCT_USB5534B,
      .bInterfaceClass = USB_CLASS_HUB,
      .driver_info = HUB_QUIRK_DISABLE_AUTOSUSPEND},
    { .match_flags = USB_DEVICE_ID_MATCH_VENDOR
                        | USB_DEVICE_ID_MATCH_INT_CLASS,
      .idVendor = USB_VENDOR_GENESYS_LOGIC,
      .bInterfaceClass = USB_CLASS_HUB,
      .driver_info = HUB_QUIRK_CHECK_PORT_AUTOSUSPEND},
    { .match_flags = USB_DEVICE_ID_MATCH_DEV_CLASS,
      .bDeviceClass = USB_CLASS_HUB},
    { .match_flags = USB_DEVICE_ID_MATCH_INT_CLASS,
      .bInterfaceClass = USB_CLASS_HUB}, 
    { }                                         /* Terminating entry */
};      
```

### Registering hub_event thread
```c
5362 static void hub_event(struct work_struct *work)
5363 {
5364         struct usb_device *hdev;
5365         struct usb_interface *intf;
5366         struct usb_hub *hub;
5367         struct device *hub_dev;
5368         u16 hubstatus;
5369         u16 hubchange;
5370         int i, ret;
5371 
5372         hub = container_of(work, struct usb_hub, events);
5373         hdev = hub->hdev;
5374         hub_dev = hub->intfdev;
5375         intf = to_usb_interface(hub_dev);
5376 
5377         dev_dbg(hub_dev, "state %d ports %d chg %04x evt %04x\n",
5378                         hdev->state, hdev->maxchild,
5379                         /* NOTE: expects max 15 ports... */
5380                         (u16) hub->change_bits[0],
5381                         (u16) hub->event_bits[0]);
5382 
5383         /* Lock the device, then check to see if we were
5384          * disconnected while waiting for the lock to succeed. */
5385         usb_lock_device(hdev);
5386         if (unlikely(hub->disconnected))
5387                 goto out_hdev_lock;
5388 
5389         /* If the hub has died, clean up after it */
5390         if (hdev->state == USB_STATE_NOTATTACHED) {
5391                 hub->error = -ENODEV;
5392                 hub_quiesce(hub, HUB_DISCONNECT);
5393                 goto out_hdev_lock;
5394         }
5395 
5396         /* Autoresume */
5397         ret = usb_autopm_get_interface(intf);
5398         if (ret) {
5399                 dev_dbg(hub_dev, "Can't autoresume: %d\n", ret);
5400                 goto out_hdev_lock;
5401         }
5402 
5403         /* If this is an inactive hub, do nothing */
5404         if (hub->quiescing)
5405                 goto out_autopm;
5406 
5407         if (hub->error) {
5408                 dev_dbg(hub_dev, "resetting for error %d\n", hub->error);
5409 
5410                 ret = usb_reset_device(hdev);
5411                 if (ret) {
5412                         dev_dbg(hub_dev, "error resetting hub: %d\n", ret);
5413                         goto out_autopm;
5414                 }
5415 
5416                 hub->nerrors = 0;
5417                 hub->error = 0;
5418         }
5419 
5420         /* deal with port status changes */
5421         for (i = 1; i <= hdev->maxchild; i++) {
5422                 struct usb_port *port_dev = hub->ports[i - 1];
5423 
5424                 if (test_bit(i, hub->event_bits)
5425                                 || test_bit(i, hub->change_bits)
5426                                 || test_bit(i, hub->wakeup_bits)) {
5427                         /*
5428                          * The get_noresume and barrier ensure that if
5429                          * the port was in the process of resuming, we
5430                          * flush that work and keep the port active for
5431                          * the duration of the port_event().  However,
5432                          * if the port is runtime pm suspended
5433                          * (powered-off), we leave it in that state, run
5434                          * an abbreviated port_event(), and move on.
5435                          */
5436                         pm_runtime_get_noresume(&port_dev->dev);
5437                         pm_runtime_barrier(&port_dev->dev);
5438                         usb_lock_port(port_dev);
5439                         port_event(hub, i);
5440                         usb_unlock_port(port_dev);
5441                         pm_runtime_put_sync(&port_dev->dev);
5442                 }
5443         }
5444 
5445         /* deal with hub status changes */
5446         if (test_and_clear_bit(0, hub->event_bits) == 0)
5447                 ;       /* do nothing */
5448         else if (hub_hub_status(hub, &hubstatus, &hubchange) < 0)
5449                 dev_err(hub_dev, "get_hub_status failed\n");
5450         else {
5451                 if (hubchange & HUB_CHANGE_LOCAL_POWER) {
5452                         dev_dbg(hub_dev, "power change\n");
5453                         clear_hub_feature(hdev, C_HUB_LOCAL_POWER);
5454                         if (hubstatus & HUB_STATUS_LOCAL_POWER)
5455                                 /* FIXME: Is this always true? */
5456                                 hub->limited_power = 1;
5457                         else
5458                                 hub->limited_power = 0;
5459                 }
5460                 if (hubchange & HUB_CHANGE_OVERCURRENT) {
5461                         u16 status = 0;
5462                         u16 unused;
5463 
5464                         dev_dbg(hub_dev, "over-current change\n");
5465                         clear_hub_feature(hdev, C_HUB_OVER_CURRENT);
5466                         msleep(500);    /* Cool down */
5467                         hub_power_on(hub, true);
5468                         hub_hub_status(hub, &status, &unused);
5469                         if (status & HUB_STATUS_OVERCURRENT)
5470                                 dev_err(hub_dev, "over-current condition\n");
5471                 }
5472         }
5473 
5474 out_autopm:
5475         /* Balance the usb_autopm_get_interface() above */
5476         usb_autopm_put_interface_no_suspend(intf);
5477 out_hdev_lock:
5478         usb_unlock_device(hdev);
5479 
5480         /* Balance the stuff in kick_hub_wq() and allow autosuspend */
5481         usb_autopm_put_interface(intf);
5482         kref_put(&hub->kref, hub_release);
5483 }
```

```c
5254 static void port_event(struct usb_hub *hub, int port1)
5255                 __must_hold(&port_dev->status_lock)
5256 {
5257         int connect_change;
5258         struct usb_port *port_dev = hub->ports[port1 - 1];
5259         struct usb_device *udev = port_dev->child;
5260         struct usb_device *hdev = hub->hdev;
5261         u16 portstatus, portchange;
5262 
5263         connect_change = test_bit(port1, hub->change_bits);
5264         clear_bit(port1, hub->event_bits);
5265         clear_bit(port1, hub->wakeup_bits);
5266 
5267         if (hub_port_status(hub, port1, &portstatus, &portchange) < 0)
5268                 return;
5269 
5270         if (portchange & USB_PORT_STAT_C_CONNECTION) {
5271                 usb_clear_port_feature(hdev, port1, USB_PORT_FEAT_C_CONNECTION);
5272                 connect_change = 1;
5273         }
5274 
5275         if (portchange & USB_PORT_STAT_C_ENABLE) {
5276                 if (!connect_change)
5277                         dev_dbg(&port_dev->dev, "enable change, status %08x\n",
5278                                         portstatus);
5279                 usb_clear_port_feature(hdev, port1, USB_PORT_FEAT_C_ENABLE);
5280 
5281                 /*
5282                  * EM interference sometimes causes badly shielded USB devices
5283                  * to be shutdown by the hub, this hack enables them again.
5284                  * Works at least with mouse driver.
5285                  */
5286                 if (!(portstatus & USB_PORT_STAT_ENABLE)
5287                     && !connect_change && udev) {
5288                         dev_err(&port_dev->dev, "disabled by hub (EMI?), re-enabling...\n");
5289                         connect_change = 1;
5290                 }
5291         }
5292 
5293         if (portchange & USB_PORT_STAT_C_OVERCURRENT) {
5294                 u16 status = 0, unused;
5295                 port_dev->over_current_count++;
5296                 port_over_current_notify(port_dev);
5297 
5298                 dev_dbg(&port_dev->dev, "over-current change #%u\n",
5299                         port_dev->over_current_count);
5300                 usb_clear_port_feature(hdev, port1,
5301                                 USB_PORT_FEAT_C_OVER_CURRENT);
5302                 msleep(100);    /* Cool down */
5303                 hub_power_on(hub, true);
5304                 hub_port_status(hub, port1, &status, &unused);
5305                 if (status & USB_PORT_STAT_OVERCURRENT)
5306                         dev_err(&port_dev->dev, "over-current condition\n");
5307         }
5308 
5309         if (portchange & USB_PORT_STAT_C_RESET) {
5310                 dev_dbg(&port_dev->dev, "reset change\n");
5311                 usb_clear_port_feature(hdev, port1, USB_PORT_FEAT_C_RESET);
5312         }
5313         if ((portchange & USB_PORT_STAT_C_BH_RESET)
5314             && hub_is_superspeed(hdev)) {
5315                 dev_dbg(&port_dev->dev, "warm reset change\n");
5316                 usb_clear_port_feature(hdev, port1,
5317                                 USB_PORT_FEAT_C_BH_PORT_RESET);
5318         }
5319         if (portchange & USB_PORT_STAT_C_LINK_STATE) {
5320                 dev_dbg(&port_dev->dev, "link state change\n");
5321                 usb_clear_port_feature(hdev, port1,
5322                                 USB_PORT_FEAT_C_PORT_LINK_STATE);
5323         }
5324         if (portchange & USB_PORT_STAT_C_CONFIG_ERROR) {
5325                 dev_warn(&port_dev->dev, "config error\n");
5326                 usb_clear_port_feature(hdev, port1,
5327                                 USB_PORT_FEAT_C_PORT_CONFIG_ERROR);
5328         }
5329 
5330         /* skip port actions that require the port to be powered on */
5331         if (!pm_runtime_active(&port_dev->dev))
5332                 return;
5333 
5334         if (hub_handle_remote_wakeup(hub, port1, portstatus, portchange))
5335                 connect_change = 1;
5336 
5337         /*
5338          * Warm reset a USB3 protocol port if it's in
5339          * SS.Inactive state.
5340          */
5341         if (hub_port_warm_reset_required(hub, port1, portstatus)) {
5342                 dev_dbg(&port_dev->dev, "do warm reset\n");
5343                 if (!udev || !(portstatus & USB_PORT_STAT_CONNECTION)
5344                                 || udev->state == USB_STATE_NOTATTACHED) {
5345                         if (hub_port_reset(hub, port1, NULL,
5346                                         HUB_BH_RESET_TIME, true) < 0)
5347                                 hub_port_disable(hub, port1, 1);
5348                 } else {
5349                         usb_unlock_port(port_dev);
5350                         usb_lock_device(udev);
5351                         usb_reset_device(udev);
5352                         usb_unlock_device(udev);
5353                         usb_lock_port(port_dev);
5354                         connect_change = 0;
5355                 }
5356         }
5357 
5358         if (connect_change)
5359                 hub_port_connect_change(hub, port1, portstatus, portchange);
5360 }

```

```c
5156 /* Handle physical or logical connection change events.
5157  * This routine is called when:
5158  *      a port connection-change occurs;
5159  *      a port enable-change occurs (often caused by EMI);
5160  *      usb_reset_and_verify_device() encounters changed descriptors (as from
5161  *              a firmware download)
5162  * caller already locked the hub
5163  */
5164 static void hub_port_connect_change(struct usb_hub *hub, int port1,
5165                                         u16 portstatus, u16 portchange)
5166                 __must_hold(&port_dev->status_lock)
5167 {
5168         struct usb_port *port_dev = hub->ports[port1 - 1];
5169         struct usb_device *udev = port_dev->child;
5170         int status = -ENODEV;
5171 
5172         dev_dbg(&port_dev->dev, "status %04x, change %04x, %s\n", portstatus,
5173                         portchange, portspeed(hub, portstatus));
5174 
5175         if (hub->has_indicators) {
5176                 set_port_led(hub, port1, HUB_LED_AUTO);
5177                 hub->indicator[port1-1] = INDICATOR_AUTO;
5178         }
5179 
5180 #ifdef  CONFIG_USB_OTG
5181         /* during HNP, don't repeat the debounce */
5182         if (hub->hdev->bus->is_b_host)
5183                 portchange &= ~(USB_PORT_STAT_C_CONNECTION |
5184                                 USB_PORT_STAT_C_ENABLE);
5185 #endif
5186 
5187         /* Try to resuscitate an existing device */
5188         if ((portstatus & USB_PORT_STAT_CONNECTION) && udev &&
5189                         udev->state != USB_STATE_NOTATTACHED) {
5190                 if (portstatus & USB_PORT_STAT_ENABLE) {
5191                         status = 0;             /* Nothing to do */
5192 #ifdef CONFIG_PM
5193                 } else if (udev->state == USB_STATE_SUSPENDED &&
5194                                 udev->persist_enabled) {
5195                         /* For a suspended device, treat this as a
5196                          * remote wakeup event.
5197                          */
5198                         usb_unlock_port(port_dev);
5199                         status = usb_remote_wakeup(udev);
5200                         usb_lock_port(port_dev);
5201 #endif
5202                 } else {
5203                         /* Don't resuscitate */;
5204                 }
5205         }
5206         clear_bit(port1, hub->change_bits);
5207 
5208         /* successfully revalidated the connection */
5209         if (status == 0)
5210                 return;
5211 
5212         usb_unlock_port(port_dev);
5213         hub_port_connect(hub, port1, portstatus, portchange);
5214         usb_lock_port(port_dev);
5215 }
```

```c
4933 static void hub_port_connect(struct usb_hub *hub, int port1, u16 portstatus,
4934                 u16 portchange)
4935 {
4936         int status = -ENODEV;
4937         int i;
4938         unsigned unit_load;
4939         struct usb_device *hdev = hub->hdev;
4940         struct usb_hcd *hcd = bus_to_hcd(hdev->bus);
4941         struct usb_port *port_dev = hub->ports[port1 - 1];
4942         struct usb_device *udev = port_dev->child;
4943         static int unreliable_port = -1;
4944 
4945         /* Disconnect any existing devices under this port */
4946         if (udev) {
4947                 if (hcd->usb_phy && !hdev->parent)
4948                         usb_phy_notify_disconnect(hcd->usb_phy, udev->speed);
4949                 usb_disconnect(&port_dev->child);
4950         }
4951 
4952         /* We can forget about a "removed" device when there's a physical
4953          * disconnect or the connect status changes.
4954          */
4955         if (!(portstatus & USB_PORT_STAT_CONNECTION) ||
4956                         (portchange & USB_PORT_STAT_C_CONNECTION))
4957                 clear_bit(port1, hub->removed_bits);
4958 
4959         if (portchange & (USB_PORT_STAT_C_CONNECTION |
4960                                 USB_PORT_STAT_C_ENABLE)) {
4961                 status = hub_port_debounce_be_stable(hub, port1);
4962                 if (status < 0) {
4963                         if (status != -ENODEV &&
4964                                 port1 != unreliable_port &&
4965                                 printk_ratelimit())
4966                                 dev_err(&port_dev->dev, "connect-debounce failed\n");
4967                         portstatus &= ~USB_PORT_STAT_CONNECTION;
4968                         unreliable_port = port1;
4969                 } else {
4970                         portstatus = status;
4971                 }
4972         }
4973 
4974         /* Return now if debouncing failed or nothing is connected or
4975          * the device was "removed".
4976          */
4977         if (!(portstatus & USB_PORT_STAT_CONNECTION) ||
4978                         test_bit(port1, hub->removed_bits)) {
4979 
4980                 /*
4981                  * maybe switch power back on (e.g. root hub was reset)
4982                  * but only if the port isn't owned by someone else.
4983                  */
4984                 if (hub_is_port_power_switchable(hub)
4985                                 && !port_is_power_on(hub, portstatus)
4986                                 && !port_dev->port_owner)
4987                         set_port_feature(hdev, port1, USB_PORT_FEAT_POWER);
4988 
4989                 if (portstatus & USB_PORT_STAT_ENABLE)
4990                         goto done;
4991                 return;
4992         }
4993         if (hub_is_superspeed(hub->hdev))
4994                 unit_load = 150;
4995         else
4996                 unit_load = 100;
4997 
4998         status = 0;
4999         for (i = 0; i < SET_CONFIG_TRIES; i++) {
5000 
5001                 /* reallocate for each attempt, since references
5002                  * to the previous one can escape in various ways
5003                  */
5004                 udev = usb_alloc_dev(hdev, hdev->bus, port1);
5005                 if (!udev) {
5006                         dev_err(&port_dev->dev,
5007                                         "couldn't allocate usb_device\n");
5008                         goto done;
5009                 }
5010 
5011                 usb_set_device_state(udev, USB_STATE_POWERED);
5012                 udev->bus_mA = hub->mA_per_port;
5013                 udev->level = hdev->level + 1;
5014                 udev->wusb = hub_is_wusb(hub);
5015 
5016                 /* Devices connected to SuperSpeed hubs are USB 3.0 or later */
5017                 if (hub_is_superspeed(hub->hdev))
5018                         udev->speed = USB_SPEED_SUPER;
5019                 else
5020                         udev->speed = USB_SPEED_UNKNOWN;
5021 
5022                 choose_devnum(udev);
5023                 if (udev->devnum <= 0) {
5024                         status = -ENOTCONN;     /* Don't retry */
5025                         goto loop;
5026                 }
5027 
5028                 /* reset (non-USB 3.0 devices) and get descriptor */
5029                 usb_lock_port(port_dev);
5030                 status = hub_port_init(hub, udev, port1, i);
5031                 usb_unlock_port(port_dev);
5032                 if (status < 0)
5033                         goto loop;
5034 
5035                 if (udev->quirks & USB_QUIRK_DELAY_INIT)
5036                         msleep(2000);
5037 
5038                 /* consecutive bus-powered hubs aren't reliable; they can
5039                  * violate the voltage drop budget.  if the new child has
5040                  * a "powered" LED, users should notice we didn't enable it
5041                  * (without reading syslog), even without per-port LEDs
5042                  * on the parent.
5043                  */
5044                 if (udev->descriptor.bDeviceClass == USB_CLASS_HUB
5045                                 && udev->bus_mA <= unit_load) {
5046                         u16     devstat;
5047 
5048                         status = usb_get_std_status(udev, USB_RECIP_DEVICE, 0,
5049                                         &devstat);
5050                         if (status) {
5051                                 dev_dbg(&udev->dev, "get status %d ?\n", status);
5052                                 goto loop_disable;
5053                         }
5054                         if ((devstat & (1 << USB_DEVICE_SELF_POWERED)) == 0) {
5055                                 dev_err(&udev->dev,
5056                                         "can't connect bus-powered hub "
5057                                         "to this port\n");
5058                                 if (hub->has_indicators) {
5059                                         hub->indicator[port1-1] =
5060                                                 INDICATOR_AMBER_BLINK;
5061                                         queue_delayed_work(
5062                                                 system_power_efficient_wq,
5063                                                 &hub->leds, 0);
5064                                 }
5065                                 status = -ENOTCONN;     /* Don't retry */
5066                                 goto loop_disable;
5067                         }
5068                 }
5069 
5070                 /* check for devices running slower than they could */
5071                 if (le16_to_cpu(udev->descriptor.bcdUSB) >= 0x0200
5072                                 && udev->speed == USB_SPEED_FULL
5073                                 && highspeed_hubs != 0)
5074                         check_highspeed(hub, udev, port1);
5075 
5076                 /* Store the parent's children[] pointer.  At this point
5077                  * udev becomes globally accessible, although presumably
5078                  * no one will look at it until hdev is unlocked.
5079                  */
5080                 status = 0;
5081 
5082                 mutex_lock(&usb_port_peer_mutex);
5083 
5084                 /* We mustn't add new devices if the parent hub has
5085                  * been disconnected; we would race with the
5086                  * recursively_mark_NOTATTACHED() routine.
5087                  */
5088                 spin_lock_irq(&device_state_lock);
5089                 if (hdev->state == USB_STATE_NOTATTACHED)
5090                         status = -ENOTCONN;
5091                 else
5092                         port_dev->child = udev;
5093                 spin_unlock_irq(&device_state_lock);
5094                 mutex_unlock(&usb_port_peer_mutex);
5095 
5096                 /* Run it through the hoops (find a driver, etc) */
5097                 if (!status) {
5098                         status = usb_new_device(udev);
5099                         if (status) {
5100                                 mutex_lock(&usb_port_peer_mutex);
5101                                 spin_lock_irq(&device_state_lock);
5102                                 port_dev->child = NULL;
5103                                 spin_unlock_irq(&device_state_lock);
5104                                 mutex_unlock(&usb_port_peer_mutex);
5105                         } else {
5106                                 if (hcd->usb_phy && !hdev->parent)
5107                                         usb_phy_notify_connect(hcd->usb_phy,
5108                                                         udev->speed);
5109                         }
5110                 }
5111 
5112                 if (status)
5113                         goto loop_disable;
5114 
5115                 status = hub_power_remaining(hub);
5116                 if (status)
5117                         dev_dbg(hub->intfdev, "%dmA power budget left\n", status);
5118 
5119                 return;
5120 
5121 loop_disable:
5122                 hub_port_disable(hub, port1, 1);
5123 loop:
5124                 usb_ep0_reinit(udev);
5125                 release_devnum(udev);
5126                 hub_free_dev(udev);
5127                 usb_put_dev(udev);
5128                 if ((status == -ENOTCONN) || (status == -ENOTSUPP))
5129                         break;
5130 
5131                 /* When halfway through our retry count, power-cycle the port */
5132                 if (i == (SET_CONFIG_TRIES / 2) - 1) {
5133                         dev_info(&port_dev->dev, "attempt power cycle\n");
5134                         usb_hub_set_port_power(hdev, hub, port1, false);
5135                         msleep(2 * hub_power_on_good_delay(hub));
5136                         usb_hub_set_port_power(hdev, hub, port1, true);
5137                         msleep(hub_power_on_good_delay(hub));
5138                 }
5139         }
5140         if (hub->hdev->parent ||
5141                         !hcd->driver->port_handed_over ||
5142                         !(hcd->driver->port_handed_over)(hcd, port1)) {
5143                 if (status != -ENOTCONN && status != -ENODEV)
5144                         dev_err(&port_dev->dev,
5145                                         "unable to enumerate USB device\n");
5146         }
5147 
5148 done:
5149         hub_port_disable(hub, port1, 1);
5150         if (hcd->driver->relinquish_port && !hub->hdev->parent) {
5151                 if (status != -ENOTCONN && status != -ENODEV)
5152                         hcd->driver->relinquish_port(hcd, port1);
5153         }
5154 }
5155 
5156 /* Handle physical or logical connection change events.
5157  * This routine is called when:
5158  *      a port connection-change occurs;
5159  *      a port enable-change occurs (often caused by EMI);
5160  *      usb_reset_and_verify_device() encounters changed descriptors (as from
5161  *              a firmware download)
5162  * caller already locked the hub
5163  */
5164 static void hub_port_connect_change(struct usb_hub *hub, int port1,
5165                                         u16 portstatus, u16 portchange)
5166                 __must_hold(&port_dev->status_lock)
5167 {
5168         struct usb_port *port_dev = hub->ports[port1 - 1];
5169         struct usb_device *udev = port_dev->child;
5170         int status = -ENODEV;
5171 
5172         dev_dbg(&port_dev->dev, "status %04x, change %04x, %s\n", portstatus,
5173                         portchange, portspeed(hub, portstatus));
5174 
5175         if (hub->has_indicators) {
5176                 set_port_led(hub, port1, HUB_LED_AUTO);
5177                 hub->indicator[port1-1] = INDICATOR_AUTO;
5178         }
5179 
5180 #ifdef  CONFIG_USB_OTG
5181         /* during HNP, don't repeat the debounce */
5182         if (hub->hdev->bus->is_b_host)
5183                 portchange &= ~(USB_PORT_STAT_C_CONNECTION |
5184                                 USB_PORT_STAT_C_ENABLE);
5185 #endif
5186 
5187         /* Try to resuscitate an existing device */
5188         if ((portstatus & USB_PORT_STAT_CONNECTION) && udev &&
5189                         udev->state != USB_STATE_NOTATTACHED) {
5190                 if (portstatus & USB_PORT_STAT_ENABLE) {
5191                         status = 0;             /* Nothing to do */
5192 #ifdef CONFIG_PM
5193                 } else if (udev->state == USB_STATE_SUSPENDED &&
5194                                 udev->persist_enabled) {
5195                         /* For a suspended device, treat this as a
5196                          * remote wakeup event.
5197                          */
5198                         usb_unlock_port(port_dev);
5199                         status = usb_remote_wakeup(udev);
5200                         usb_lock_port(port_dev);
5201 #endif
5202                 } else {
5203                         /* Don't resuscitate */;
5204                 }
5205         }
5206         clear_bit(port1, hub->change_bits);
5207 
5208         /* successfully revalidated the connection */
5209         if (status == 0)
5210                 return;
5211 
5212         usb_unlock_port(port_dev);
5213         hub_port_connect(hub, port1, portstatus, portchange);
5214         usb_lock_port(port_dev);
5215 }
```



### Add new device
```c
2482 int usb_new_device(struct usb_device *udev)
2483 {
2484     int err;
2485 
2486     if (udev->parent) {
2487         /* Initialize non-root-hub device wakeup to disabled;
2488          * device (un)configuration controls wakeup capable
2489          * sysfs power/wakeup controls wakeup enabled/disabled
2490          */
2491         device_init_wakeup(&udev->dev, 0);
2492     }
2493 
2494     /* Tell the runtime-PM framework the device is active */
2495     pm_runtime_set_active(&udev->dev);
2496     pm_runtime_get_noresume(&udev->dev);
2497     pm_runtime_use_autosuspend(&udev->dev);
2498     pm_runtime_enable(&udev->dev);
2499 
2500     /* By default, forbid autosuspend for all devices.  It will be
2501      * allowed for hubs during binding.
2502      */
2503     usb_disable_autosuspend(udev);
2504 
2505     err = usb_enumerate_device(udev);   /* Read descriptors */
2506     if (err < 0)
2507         goto fail;
2508     dev_dbg(&udev->dev, "udev %d, busnum %d, minor = %d\n",
2509             udev->devnum, udev->bus->busnum,
2510             (((udev->bus->busnum-1) * 128) + (udev->devnum-1)));
2511     /* export the usbdev device-node for libusb */
2512     udev->dev.devt = MKDEV(USB_DEVICE_MAJOR,
2513             (((udev->bus->busnum-1) * 128) + (udev->devnum-1)));
2514 
2515     /* Tell the world! */
2516     announce_device(udev);
2517 
2518     if (udev->serial)
2519         add_device_randomness(udev->serial, strlen(udev->serial));
2520     if (udev->product)
2521         add_device_randomness(udev->product, strlen(udev->product));
2522     if (udev->manufacturer)
2523         add_device_randomness(udev->manufacturer,
2524                       strlen(udev->manufacturer));
2525 
2526     device_enable_async_suspend(&udev->dev);
2527 
2528     /* check whether the hub or firmware marks this port as non-removable */
2529     if (udev->parent)
2530         set_usb_port_removable(udev);
2531 
2532     /* Register the device.  The device driver is responsible
2533      * for configuring the device and invoking the add-device
2534      * notifier chain (used by usbfs and possibly others).
2535      */
2536     err = device_add(&udev->dev);
2537     if (err) {
2538         dev_err(&udev->dev, "can't device_add, error %d\n", err);
2539         goto fail;
2540     }
2541 
2542     /* Create link files between child device and usb port device. */
2543     if (udev->parent) {
2544         struct usb_hub *hub = usb_hub_to_struct_hub(udev->parent);
2545         int port1 = udev->portnum;
2546         struct usb_port *port_dev = hub->ports[port1 - 1];
2547 
2548         err = sysfs_create_link(&udev->dev.kobj,
2549                 &port_dev->dev.kobj, "port");
2550         if (err)
2551             goto fail;
2552 
2553         err = sysfs_create_link(&port_dev->dev.kobj,
2554                 &udev->dev.kobj, "device");
2555         if (err) {
2556             sysfs_remove_link(&udev->dev.kobj, "port");
2557             goto fail;
2558         }
2559 
2560         if (!test_and_set_bit(port1, hub->child_usage_bits))
2561             pm_runtime_get_sync(&port_dev->dev);
2562     }
2563 
2564     (void) usb_create_ep_devs(&udev->dev, &udev->ep0, udev);
2565     usb_mark_last_busy(udev);
2566     pm_runtime_put_sync_autosuspend(&udev->dev);
2567     return err;
2568 
2569 fail:
2570     usb_set_device_state(udev, USB_STATE_NOTATTACHED);
2571     pm_runtime_disable(&udev->dev);
2572     pm_runtime_set_suspended(&udev->dev);
2573     return err;
2574 }
```


## Register usb device drivers
```c
struct usb_device_driver usb_generic_driver = {
        .name = "usb",
        .match = usb_generic_driver_match,
        .probe = usb_generic_driver_probe,
        .disconnect = usb_generic_driver_disconnect,
#ifdef  CONFIG_PM
        .suspend = usb_generic_driver_suspend,
        .resume = usb_generic_driver_resume,
#endif
        .supports_autosuspend = 1,
};


/**
 * usb_register_device_driver - register a USB device (not interface) driver
 * @new_udriver: USB operations for the device driver
 * @owner: module owner of this driver.
 *
 * Registers a USB device driver with the USB core.  The list of
 * unattached devices will be rescanned whenever a new driver is
 * added, allowing the new driver to attach to any recognized devices.
 *
 * Return: A negative error code on failure and 0 on success.
 */
int usb_register_device_driver(struct usb_device_driver *new_udriver,
                struct module *owner)
{
        int retval = 0;

        if (usb_disabled())
                return -ENODEV;

        new_udriver->drvwrap.for_devices = 1;
        new_udriver->drvwrap.driver.name = new_udriver->name;
        new_udriver->drvwrap.driver.bus = &usb_bus_type;
        new_udriver->drvwrap.driver.probe = usb_probe_device;
        new_udriver->drvwrap.driver.remove = usb_unbind_device;
        new_udriver->drvwrap.driver.owner = owner;
        new_udriver->drvwrap.driver.dev_groups = new_udriver->dev_groups;

        retval = driver_register(&new_udriver->drvwrap.driver);

        if (!retval) {
                pr_info("%s: registered new device driver %s\n",
                        usbcore_name, new_udriver->name);
                /*
                 * Check whether any device could be better served with
                 * this new driver
                 */
                bus_for_each_dev(&usb_bus_type, NULL, new_udriver,
                                 __usb_bus_reprobe_drivers);
        } else {
                pr_err("%s: error %d registering device driver %s\n",
                        usbcore_name, retval, new_udriver->name);
        }

        return retval;
}
EXPORT_SYMBOL_GPL(usb_register_device_driver);
```
Note that this function is slightly different 
from usb_register_driver function
which was used for 
registering usb core interface drivers
such as hub_driver, usbfs_driver.
One of the notable difference is for_device field is only set 
for the usb_generic_driver, and other interface driver 
doesn't set the flag.
Also differnet call back functions are set for this driver
XXX
The other biggest difference is 
it invokes __usb_bus_reprobe_drivers function 
for devices registered on the usb bus.

# Long journey to understand how the USB device can be hot-plugged
Although most basic usb core part and usb bus
have been initialized at the boot-up,
the internal usb controllers and another 
layers of device driver should be bound
to fully manage the usb subsystem. 

Previous initializations are mostly focused on the 
usb core parts that provides 
generic software layers for usb management 
regardless of the hardware specification of the internal usb controller.

However, the first layer that actually encounters
usb attachment and detachment is the usb controller.
As usb specification develops, 
its controller implementing the specifications also evolved,
and linux supports various usb controllers. 

First to understand the linux-supporting usb controllers,
you have to clearly distinguish 
usb host controller interface from actual usb controller.
There are four typical host controller interfaces supported by Linux:
*OHCI (Open Host Controller Interface(Compaq)) supporting only USB1.1 (Full and Low speeds),
*UHCI (Universal Host Controller Interface (Intel)) supporting 1.x(Full and Low speeds). 
The hardware composition of UHCI is simple which makes its driver more complex burdening your processor.
*EHCI (Extended Host Controller Interface) supporting USB 2.0.
*XHCI (Extended Host Controller Interface) supporting USB 3.x and belows for compatibility (including 2.0, 1.X)

XXX
Although there is only one fixed specification for a particular USB version, 
there can be various versions of USB controller 
that implements particular specifications. 
Therefore, 
to support those controllers,
device driver should be required.
For example,
the linux provides device driver supports for DWC3 
which is 
SuperSpeed (SS) USB 3.0 Dual-Role-Device (DRD) from Synopsys.
Also, it has support for CDNS3
which is a SuperSpeed (SS) USB 3.0 Dual-Role-Device (DRD) controller from Cadence.
Furthermore, 
note that there can be more device specific USB micro controller
that is not supported by the linux officially. 
For further information about Linux supported USB controller,
take a look at usb directory.



## The USB Host controller drivers
There are various usb controllers 
implemented by the different vendors 
even though they support same USB specification.
Therefore, to reduce the boilerplate in
multiple host controller driver,
linux implementes generic host controller code 
that can support multiple versions of it. 

```c
struct usb_hcd {

        /*
         * housekeeping
         */
        struct usb_bus          self;           /* hcd is-a bus */
        struct kref             kref;           /* reference counter */

        const char              *product_desc;  /* product/vendor string */
        int                     speed;          /* Speed for this roothub.
                                                 * May be different from
                                                 * hcd->driver->flags & HCD_MASK
                                                 */
        char                    irq_descr[24];  /* driver + bus # */

        struct timer_list       rh_timer;       /* drives root-hub polling */
        struct urb              *status_urb;    /* the current status urb */
#ifdef CONFIG_PM
        struct work_struct      wakeup_work;    /* for remote wakeup */
#endif
        struct work_struct      died_work;      /* for when the device dies */

        /*
         * hardware info/state
         */
        const struct hc_driver  *driver;        /* hw-specific hooks */
	...

}
```
Usb_hcd structure maintains general information
required for managing USB controllers 
regradless of its specification versions and vendors. 
Therefore, 
to utilize the benefit of Linux USB subsystem,
each host controller driver should provide
all information required by generic usb_hcd structure.


### xHCI usb specification 
Let's switch gears and take a look at 
USB specification, particularly xHCI. 
At the time of writing this posting,
the xHCI usb specification is the up-to-date version of USB
supporting usb3.x and belows such as usb1.x and usb 2.0.

The USB specification is a essential information
to represent a particular USB host controller device.
You can see that 
usb_hcd structure contains the hc_driver structure pointer
in the above code block.
This structure contains USB specification specific callback functions 
utilized by the USB host controller driver 
to support specific USB protocol such as USB 3.0, USB 2.0, etc. 

**drivers/usb/host/xhci.c file**
```c
static const struct hc_driver xhci_hc_driver = {
        .description =          "xhci-hcd",
        .product_desc =         "xHCI Host Controller",
        .hcd_priv_size =        sizeof(struct xhci_hcd),

        /*
         * generic hardware linkage
         */
        .irq =                  xhci_irq,
        .flags =                HCD_MEMORY | HCD_DMA | HCD_USB3 | HCD_SHARED |
                                HCD_BH,

        /*
         * basic lifecycle operations
         */
        .reset =                NULL, /* set in xhci_init_driver() */
        .start =                xhci_run,
        .stop =                 xhci_stop,
        .shutdown =             xhci_shutdown,

        /*
         * managing i/o requests and associated device resources
         */
        .map_urb_for_dma =      xhci_map_urb_for_dma,
        .unmap_urb_for_dma =    xhci_unmap_urb_for_dma,
        .urb_enqueue =          xhci_urb_enqueue,
        .urb_dequeue =          xhci_urb_dequeue,
        .alloc_dev =            xhci_alloc_dev,
        .free_dev =             xhci_free_dev,
        .alloc_streams =        xhci_alloc_streams,
        .free_streams =         xhci_free_streams,
        .add_endpoint =         xhci_add_endpoint,
        .drop_endpoint =        xhci_drop_endpoint,
        .endpoint_disable =     xhci_endpoint_disable,
        .endpoint_reset =       xhci_endpoint_reset,
        .check_bandwidth =      xhci_check_bandwidth,
        .reset_bandwidth =      xhci_reset_bandwidth,
        .address_device =       xhci_address_device,
        .enable_device =        xhci_enable_device,
        .update_hub_device =    xhci_update_hub_device,
        .reset_device =         xhci_discover_or_reset_device,

        /*
         * scheduling support
         */
        .get_frame_number =     xhci_get_frame,

        /*
         * root hub support
         */
        .hub_control =          xhci_hub_control,
        .hub_status_data =      xhci_hub_status_data,
        .bus_suspend =          xhci_bus_suspend,
        .bus_resume =           xhci_bus_resume,
        .get_resuming_ports =   xhci_get_resuming_ports,

        /*
         * call back when device connected and addressed
         */
        .update_device =        xhci_update_device,
        .set_usb2_hw_lpm =      xhci_set_usb2_hardware_lpm,
        .enable_usb3_lpm_timeout =      xhci_enable_usb3_lpm_timeout,
        .disable_usb3_lpm_timeout =     xhci_disable_usb3_lpm_timeout,
        .find_raw_port_number = xhci_find_raw_port_number,
        .clear_tt_buffer_complete = xhci_clear_tt_buffer_complete,
};
```
Because various USB controllers can adopt the xHCI specification,
to reduce boiler plate code,
Linux developers already implemented the generic operations
required to support xHCI spec. 

When one has reference to the xhci_hc_driver
it can utilize all xHCI provided functionalities 
and doesn't need to implement xHCI protocol 
on its driver implementation once again. 

```c
void xhci_init_driver(struct hc_driver *drv,
                      const struct xhci_driver_overrides *over)
{
        BUG_ON(!over);

        /* Copy the generic table to drv then apply the overrides */
        *drv = xhci_hc_driver;

        if (over) {
                drv->hcd_priv_size += over->extra_priv_size;
                if (over->reset)
                        drv->reset = over->reset;
                if (over->start)
                        drv->start = over->start;
        }
}
EXPORT_SYMBOL_GPL(xhci_init_driver);
```
The xHCI driver implementing the xhci_hc_driver doesn't consume this structure,
but provide it to other drivers who want to utilize the xHCI specification.
In other words, 
xHCI driver is not designed to be bound to specific hardware module,
but a just kernel level driver 
designed to supports other usb host controllers.
To acheive that, it exports function *xhci_init_driver*.
When other device driver invokes this function,
the xhci_hc_driver's reference is returned.

### xHCI platform driver
```c
static struct platform_driver usb_xhci_driver = {
        .probe  = xhci_plat_probe,
        .remove = xhci_plat_remove,
        .shutdown = usb_hcd_platform_shutdown,
        .driver = {
                .name = "xhci-hcd",
                .pm = &xhci_plat_pm_ops,
                .of_match_table = of_match_ptr(usb_xhci_of_match),
                .acpi_match_table = ACPI_PTR(usb_xhci_acpi_match),
        },
};
MODULE_ALIAS("platform:xhci-hcd");

static int __init xhci_plat_init(void)
{
        xhci_init_driver(&xhci_plat_hc_driver, &xhci_plat_overrides);
        return platform_driver_register(&usb_xhci_driver);
}

void xhci_init_driver(struct hc_driver *drv,
                      const struct xhci_driver_overrides *over)
{
        BUG_ON(!over);

        /* Copy the generic table to drv then apply the overrides */
        *drv = xhci_hc_driver;

        if (over) {
                drv->hcd_priv_size += over->extra_priv_size;
                if (over->reset)
                        drv->reset = over->reset;
                if (over->start)
                        drv->start = over->start;
        }
}
EXPORT_SYMBOL_GPL(xhci_init_driver);
```
The paltform driver for xHCI host controller interface
invokes xhci_init_driver in its driver init function.
This allows the xhci-hcd driver to get reference of the xHCI core object for hc_driver, and 
also register the driver itself as platform driver.
Note that usb_xhci_driver is a driver for platform xHCI controller. 



### DWC3
DWC3 is a SuperSpeed USB 3.0 controller developed by 
the Synopsys DesignWare.
In this posting this USB controller is used in our SoC
and probed by the device tree.

```c
#ifdef CONFIG_OF
static const struct of_device_id of_dwc3_match[] = {
        {
                .compatible = "snps,dwc3"
        },
        {
                .compatible = "synopsys,dwc3"
        },
        { },
};
MODULE_DEVICE_TABLE(of, of_dwc3_match);

static struct platform_driver dwc3_driver = {
        .probe          = dwc3_probe,
        .remove         = dwc3_remove,
        .driver         = {
                .name   = "dwc3",
                .of_match_table = of_match_ptr(of_dwc3_match),
                .acpi_match_table = ACPI_PTR(dwc3_acpi_match),
                .pm     = &dwc3_dev_pm_ops,
        },
};
module_platform_driver(dwc3_driver);
```

When a device node in the device tree
has compatilbe string one of "snps,dwc3" or "synopsys,dwc3"
the pre-designated probe function, dwc3_probe will be invoked.

### DWC3 probe function
Let's take a look at what happens when the DWC3 controller is found. 

```c
static int dwc3_probe(struct platform_device *pdev)
{
        struct device           *dev = &pdev->dev;
        struct resource         *res, dwc_res;
        struct dwc3             *dwc;

        int                     ret;

        void __iomem            *regs;

        dwc = devm_kzalloc(dev, sizeof(*dwc), GFP_KERNEL);
        if (!dwc)
                return -ENOMEM;

        dwc->dev = dev;

        res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
        if (!res) {
                dev_err(dev, "missing memory resource\n");
                return -ENODEV;
        }

        dwc->xhci_resources[0].start = res->start;
        dwc->xhci_resources[0].end = dwc->xhci_resources[0].start +
                                        DWC3_XHCI_REGS_END;
        dwc->xhci_resources[0].flags = res->flags;
        dwc->xhci_resources[0].name = res->name;

        /*
         * Request memory region but exclude xHCI regs,
         * since it will be requested by the xhci-plat driver.
         */
        dwc_res = *res;
        dwc_res.start += DWC3_GLOBALS_REGS_START;

        regs = devm_ioremap_resource(dev, &dwc_res);
        if (IS_ERR(regs))
                return PTR_ERR(regs);

        dwc->regs       = regs;
        dwc->regs_size  = resource_size(&dwc_res);

        dwc3_get_properties(dwc);

        dma_set_mask_and_coherent(dev, DMA_BIT_MASK(dwc->dma_mask_bits));

        dwc->reset = devm_reset_control_array_get(dev, true, true);
        if (IS_ERR(dwc->reset))
                return PTR_ERR(dwc->reset);

        if (dev->of_node) {
                ret = devm_clk_bulk_get_all(dev, &dwc->clks);
                if (ret == -EPROBE_DEFER)
                        return ret;
                /*
                 * Clocks are optional, but new DT platforms should support all
                 * clocks as required by the DT-binding.
                 */
                if (ret < 0)
                        dwc->num_clks = 0;
                else
                        dwc->num_clks = ret;

        }
        ret = reset_control_deassert(dwc->reset);
        if (ret)
                return ret;

        ret = clk_bulk_prepare_enable(dwc->num_clks, dwc->clks);
        if (ret)
                goto assert_reset;

        if (!dwc3_core_is_valid(dwc)) { 
                dev_err(dwc->dev, "this is not a DesignWare USB3 DRD Core\n");
                ret = -ENODEV;
                goto disable_clks;
        }

        platform_set_drvdata(pdev, dwc);
        dwc3_cache_hwparams(dwc);

        spin_lock_init(&dwc->lock);

        pm_runtime_set_active(dev);
        pm_runtime_use_autosuspend(dev);
        pm_runtime_set_autosuspend_delay(dev, DWC3_DEFAULT_AUTOSUSPEND_DELAY);
        pm_runtime_enable(dev);
        ret = pm_runtime_get_sync(dev);
        if (ret < 0)
                goto err1;

        pm_runtime_forbid(dev);

        ret = dwc3_alloc_event_buffers(dwc, DWC3_EVENT_BUFFERS_SIZE);
        if (ret) {
                dev_err(dwc->dev, "failed to allocate event buffers\n");
                ret = -ENOMEM;
                goto err2;
        }

        ret = dwc3_get_dr_mode(dwc);
        if (ret)
                goto err3;

        ret = dwc3_alloc_scratch_buffers(dwc);
        if (ret)
                goto err3;

        ret = dwc3_core_init(dwc);
        if (ret) {
                if (ret != -EPROBE_DEFER)
                        dev_err(dev, "failed to initialize core: %d\n", ret);
                goto err4;
        }

        dwc3_check_params(dwc);

        ret = dwc3_core_init_mode(dwc);
        if (ret)
                goto err5;

        dwc3_debugfs_init(dwc);
        pm_runtime_put(dev);

        return 0;
	...
}
```
The first priority of the dwc3_probe function is 
retrieving the memory mapped address of the dwc3 USB controller. 
This address should be specified in the device node of the DWC3 controller. 
When you look at the binding of the DWC3,
you can easily find that 
the first reg value of the DWC3 binding is 
a memory address of the DWC3 controller mapped on that system.
Therefore, by invoking *res = platform_get_resource(pdev, IORESOURCE_MEM, 0)*
you can retrieve the memory mapped address of the DWC3 controller.

This address region not only contains xHCI information, but also DWC3 specific registers. 
Because we will defer to the xHCI driver 
on discovering its registers and configuring xHCI specific settings,
we will skip the memory region containing the xHCI registers
by adding predefined DWC3 offset
(dwc_res.start += DWC3_GLOBALS_REGS_START).

Because currently accessible address is physically mapped DWC3 register address,
we need to let the kernel translate this address and 
generate kernel virtual address. 
To achieve it,
it invoke sdevm_ioremap_resource function. 
After this function is invokes, 
we can access the DWC3 register as if
it resides on the virtual memory of the kernel. 

After the successful ioremap,
dwc3_cache_hwparams function reads the DWC3 configuration registers 
and stores them in the dwc3 structure object
as a cache.
The reason of having cache is reading those information from the actual memory
is much faster than reading them from the memory mapped DWC3's actual registers.
```c
static void dwc3_cache_hwparams(struct dwc3 *dwc)
{
        struct dwc3_hwparams    *parms = &dwc->hwparams;

        parms->hwparams0 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS0);
        parms->hwparams1 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS1);
        parms->hwparams2 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS2);
        parms->hwparams3 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS3);
        parms->hwparams4 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS4);
        parms->hwparams5 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS5);
        parms->hwparams6 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS6);
        parms->hwparams7 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS7);
        parms->hwparams8 = dwc3_readl(dwc->regs, DWC3_GHWPARAMS8);
}
```
The registers read by the above function are 
GHWPARAMS0 to GHWPARAMS7 which are Global Hardware Parameters registers.
These registers contain all the information
required to initialize the DWC3 device driver.
The detailed information about those registers are described in the DWC3 specification.

The GHWPARAMS0 register read from dwc3_cache_hwparams function
is used to determine the mode of the DWC3 controller.
There are three different types of mode:
Device-only, Host-only, and  Dual-role device (DRD).

```c
static int dwc3_get_dr_mode(struct dwc3 *dwc)
{
        enum usb_dr_mode mode;
        struct device *dev = dwc->dev;
        unsigned int hw_mode;

        if (dwc->dr_mode == USB_DR_MODE_UNKNOWN)
                dwc->dr_mode = USB_DR_MODE_OTG;

        mode = dwc->dr_mode;
        hw_mode = DWC3_GHWPARAMS0_MODE(dwc->hwparams.hwparams0);

        switch (hw_mode) {
        case DWC3_GHWPARAMS0_MODE_GADGET:
                if (IS_ENABLED(CONFIG_USB_DWC3_HOST)) {
                        dev_err(dev,
                                "Controller does not support host mode.\n");
                        return -EINVAL;
                }
                mode = USB_DR_MODE_PERIPHERAL;
                break;
        case DWC3_GHWPARAMS0_MODE_HOST:
                if (IS_ENABLED(CONFIG_USB_DWC3_GADGET)) {
                        dev_err(dev,
                                "Controller does not support device mode.\n");
                        return -EINVAL;
                }
                mode = USB_DR_MODE_HOST;
                break;
        default:
                if (IS_ENABLED(CONFIG_USB_DWC3_HOST))
                        mode = USB_DR_MODE_HOST;
                else if (IS_ENABLED(CONFIG_USB_DWC3_GADGET))
                        mode = USB_DR_MODE_PERIPHERAL;

                /*
                 * DWC_usb31 and DWC_usb3 v3.30a and higher do not support OTG
                 * mode. If the controller supports DRD but the dr_mode is not
                 * specified or set to OTG, then set the mode to peripheral.
                 */
                if (mode == USB_DR_MODE_OTG &&
                    (!IS_ENABLED(CONFIG_USB_ROLE_SWITCH) ||
                     !device_property_read_bool(dwc->dev, "usb-role-switch")) &&
                    !DWC3_VER_IS_PRIOR(DWC3, 330A))
                        mode = USB_DR_MODE_PERIPHERAL;
        }

        if (mode != dwc->dr_mode) {
                dev_warn(dev,
                         "Configuration mismatch. dr_mode forced to %s\n",
                         mode == USB_DR_MODE_HOST ? "host" : "gadget");

                dwc->dr_mode = mode;
        }

        return 0;
}
```
The above function determines the operation mode of the DWC3
Based on this mode, dwc3 core can be initialized in different way.

```c
tatic int dwc3_core_init_mode(struct dwc3 *dwc)
{
        struct device *dev = dwc->dev;
        int ret;

        switch (dwc->dr_mode) {
        case USB_DR_MODE_PERIPHERAL:
                dwc3_set_prtcap(dwc, DWC3_GCTL_PRTCAP_DEVICE);

                if (dwc->usb2_phy)
                        otg_set_vbus(dwc->usb2_phy->otg, false);
                phy_set_mode(dwc->usb2_generic_phy, PHY_MODE_USB_DEVICE);
                phy_set_mode(dwc->usb3_generic_phy, PHY_MODE_USB_DEVICE);

                ret = dwc3_gadget_init(dwc);
                if (ret) {
                        if (ret != -EPROBE_DEFER)
                                dev_err(dev, "failed to initialize gadget\n");
                        eeturn ret;
                }
                break;
        case USB_DR_MODE_HOST:
                dwc3_set_prtcap(dwc, DWC3_GCTL_PRTCAP_HOST);

                if (dwc->usb2_phy)
                        otg_set_vbus(dwc->usb2_phy->otg, true);
                phy_set_mode(dwc->usb2_generic_phy, PHY_MODE_USB_HOST);
                phy_set_mode(dwc->usb3_generic_phy, PHY_MODE_USB_HOST);

                ret = dwc3_host_init(dwc);
                if (ret) {
                        if (ret != -EPROBE_DEFER)
                                dev_err(dev, "failed to initialize host\n");
                        return ret;
                }
                break;
        case USB_DR_MODE_OTG:
                INIT_WORK(&dwc->drd_work, __dwc3_set_mode);
                ret = dwc3_drd_init(dwc);
                if (ret) {
                        if (ret != -EPROBE_DEFER)
                                dev_err(dev, "failed to initialize dual-role\n");
                        return ret;
                }
                break;
        default:
                dev_err(dev, "Unsupported mode of operation %d\n", dwc->dr_mode);
                return -EINVAL;
        }

        return 0;
}
```
When the dr_mode is set as USB_DR_MODE_HOST,
it invokes dwc_host_init function
which register xHCI device!

### dwc3 host init-allocate xhci-hcd platform device
```c
int dwc3_host_init(struct dwc3 *dwc)
{
        struct property_entry   props[4];
        struct platform_device  *xhci;
        int                     ret, irq;
        struct resource         *res;
        struct platform_device  *dwc3_pdev = to_platform_device(dwc->dev);
        int                     prop_idx = 0;

        irq = dwc3_host_get_irq(dwc);
        if (irq < 0)
                return irq;

        res = platform_get_resource_byname(dwc3_pdev, IORESOURCE_IRQ, "host");
        if (!res)
                res = platform_get_resource_byname(dwc3_pdev, IORESOURCE_IRQ,
                                "dwc_usb3");
        if (!res)
                res = platform_get_resource(dwc3_pdev, IORESOURCE_IRQ, 0);
        if (!res)
                return -ENOMEM;

        dwc->xhci_resources[1].start = irq;
        dwc->xhci_resources[1].end = irq;
        dwc->xhci_resources[1].flags = res->flags;
        dwc->xhci_resources[1].name = res->name;

        xhci = platform_device_alloc("xhci-hcd", PLATFORM_DEVID_AUTO);
        if (!xhci) {
                dev_err(dwc->dev, "couldn't allocate xHCI device\n");
                return -ENOMEM;
        }

        xhci->dev.parent        = dwc->dev;
        ACPI_COMPANION_SET(&xhci->dev, ACPI_COMPANION(dwc->dev));

        dwc->xhci = xhci;

        ret = platform_device_add_resources(xhci, dwc->xhci_resources,
                                                DWC3_XHCI_RESOURCES_NUM);
        if (ret) {
                dev_err(dwc->dev, "couldn't add resources to xHCI device\n");
                goto err;
        }

        memset(props, 0, sizeof(struct property_entry) * ARRAY_SIZE(props));

        if (dwc->usb3_lpm_capable)
                props[prop_idx++] = PROPERTY_ENTRY_BOOL("usb3-lpm-capable");

        if (dwc->usb2_lpm_disable)
                props[prop_idx++] = PROPERTY_ENTRY_BOOL("usb2-lpm-disable");

        /**
         * WORKAROUND: dwc3 revisions <=3.00a have a limitation
         * where Port Disable command doesn't work.
         *
         * The suggested workaround is that we avoid Port Disable
         * completely.
         *
         * This following flag tells XHCI to do just that.
         */
        if (DWC3_VER_IS_WITHIN(DWC3, ANY, 300A))
                props[prop_idx++] = PROPERTY_ENTRY_BOOL("quirk-broken-port-ped");

        if (prop_idx) {
                ret = platform_device_add_properties(xhci, props);
                if (ret) {
                        dev_err(dwc->dev, "failed to add properties to xHCI\n");
                        goto err;
                }
        }

        ret = platform_device_add(xhci);
        if (ret) {
                dev_err(dwc->dev, "failed to register xHCI device\n");
                goto err;
        }

        return 0;
err:
        platform_device_put(xhci);
        return ret;
}
```
It invokes platform_device_alloc("xhci-hcd", PLATFORM_DEVID_AUTO) function
which allocates and register the platform device.
Note that the device name "xhci-hcd" is the name of the device driver 
that we've explored before.
Yes this is the name of usb_xhci_driver
which will be used to bind the allocated device to the driver. 
After the xHCI device is allocated,
it registers the generated device to the platform bus
by invoking platform_device_add function.
This function invokes device_add function, and
because the autoprobe flag is enabled for the platform bus,
its corresponding driver's bind function will be invoked.  

## Let's go back to usb_xhi_driver again!
Because the generated platform device doesn't have of_match table,
it will utilize the name of the device "xhci-hcd" and
will bound to the usb_xhci_driver.

```c
static int xhci_plat_probe(struct platform_device *pdev)
{
        const struct xhci_plat_priv *priv_match;
        const struct hc_driver  *driver;
        struct device           *sysdev, *tmpdev;
        struct xhci_hcd         *xhci;
        struct resource         *res;
        struct usb_hcd          *hcd;
        int                     ret;
        int                     irq;
        struct xhci_plat_priv   *priv = NULL;


        if (usb_disabled())
                return -ENODEV;

        driver = &xhci_plat_hc_driver;

        irq = platform_get_irq(pdev, 0);
        if (irq < 0)
                return irq;

        /*
         * sysdev must point to a device that is known to the system firmware
         * or PCI hardware. We handle these three cases here:
         * 1. xhci_plat comes from firmware
         * 2. xhci_plat is child of a device from firmware (dwc3-plat)
         * 3. xhci_plat is grandchild of a pci device (dwc3-pci)
         */
        for (sysdev = &pdev->dev; sysdev; sysdev = sysdev->parent) {
                if (is_of_node(sysdev->fwnode) ||
                        is_acpi_device_node(sysdev->fwnode))
                        break;
#ifdef CONFIG_PCI
                else if (sysdev->bus == &pci_bus_type)
                        break;
#endif
        }

        if (!sysdev)
                sysdev = &pdev->dev;

        /* Try to set 64-bit DMA first */
        if (WARN_ON(!sysdev->dma_mask))
                /* Platform did not initialize dma_mask */
                ret = dma_coerce_mask_and_coherent(sysdev,
                                                   DMA_BIT_MASK(64));
        else
                ret = dma_set_mask_and_coherent(sysdev, DMA_BIT_MASK(64));

        /* If seting 64-bit DMA mask fails, fall back to 32-bit DMA mask */
        if (ret) {
                ret = dma_set_mask_and_coherent(sysdev, DMA_BIT_MASK(32));
                if (ret)
                        return ret;
        }

        pm_runtime_set_active(&pdev->dev);
        pm_runtime_enable(&pdev->dev);
        pm_runtime_get_noresume(&pdev->dev);

        hcd = __usb_create_hcd(driver, sysdev, &pdev->dev,
                               dev_name(&pdev->dev), NULL);
        if (!hcd) {
                ret = -ENOMEM;
                goto disable_runtime;
        }

        hcd->regs = devm_platform_get_and_ioremap_resource(pdev, 0, &res);
        if (IS_ERR(hcd->regs)) {
                ret = PTR_ERR(hcd->regs);
                goto put_hcd;
        }

        hcd->rsrc_start = res->start;
        hcd->rsrc_len = resource_size(res);

        xhci = hcd_to_xhci(hcd);

        /*
         * Not all platforms have clks so it is not an error if the
         * clock do not exist.
         */
        xhci->reg_clk = devm_clk_get_optional(&pdev->dev, "reg");
        if (IS_ERR(xhci->reg_clk)) {
                ret = PTR_ERR(xhci->reg_clk);
                goto put_hcd;
        }

        ret = clk_prepare_enable(xhci->reg_clk);
        if (ret)
                goto put_hcd;

        xhci->clk = devm_clk_get_optional(&pdev->dev, NULL);
        if (IS_ERR(xhci->clk)) {
                ret = PTR_ERR(xhci->clk);
                goto disable_reg_clk;
        }

        ret = clk_prepare_enable(xhci->clk);
        if (ret)
                goto disable_reg_clk;

        if (pdev->dev.of_node)
                priv_match = of_device_get_match_data(&pdev->dev);
        else
                priv_match = dev_get_platdata(&pdev->dev);

        if (priv_match) {
                priv = hcd_to_xhci_priv(hcd);
                /* Just copy data for now */
                *priv = *priv_match;
        }

        device_set_wakeup_capable(&pdev->dev, true);

        xhci->main_hcd = hcd;
        xhci->shared_hcd = __usb_create_hcd(driver, sysdev, &pdev->dev,
                        dev_name(&pdev->dev), hcd);
        if (!xhci->shared_hcd) {
                ret = -ENOMEM;
                goto disable_clk;
        }

        /* imod_interval is the interrupt moderation value in nanoseconds. */
        xhci->imod_interval = 40000;

        /* Iterate over all parent nodes for finding quirks */
        for (tmpdev = &pdev->dev; tmpdev; tmpdev = tmpdev->parent) {

                if (device_property_read_bool(tmpdev, "usb2-lpm-disable"))
                        xhci->quirks |= XHCI_HW_LPM_DISABLE;

                if (device_property_read_bool(tmpdev, "usb3-lpm-capable"))
                        xhci->quirks |= XHCI_LPM_SUPPORT;

                if (device_property_read_bool(tmpdev, "quirk-broken-port-ped"))
                        xhci->quirks |= XHCI_BROKEN_PORT_PED;

                device_property_read_u32(tmpdev, "imod-interval-ns",
                                         &xhci->imod_interval);
        }

        hcd->usb_phy = devm_usb_get_phy_by_phandle(sysdev, "usb-phy", 0);
        if (IS_ERR(hcd->usb_phy)) {
                ret = PTR_ERR(hcd->usb_phy);
                if (ret == -EPROBE_DEFER)
                        goto put_usb3_hcd;
                hcd->usb_phy = NULL;
        } else {
                ret = usb_phy_init(hcd->usb_phy);
                if (ret)
                        goto put_usb3_hcd;
        }

        hcd->tpl_support = of_usb_host_tpl_support(sysdev->of_node);
        xhci->shared_hcd->tpl_support = hcd->tpl_support;
        if (priv && (priv->quirks & XHCI_SKIP_PHY_INIT))
                hcd->skip_phy_initialization = 1;

        if (priv && (priv->quirks & XHCI_SG_TRB_CACHE_SIZE_QUIRK))
                xhci->quirks |= XHCI_SG_TRB_CACHE_SIZE_QUIRK;

        ret = usb_add_hcd(hcd, irq, IRQF_SHARED);
        if (ret)
                goto disable_usb_phy;

        if (HCC_MAX_PSA(xhci->hcc_params) >= 4)
                xhci->shared_hcd->can_do_streams = 1;

        ret = usb_add_hcd(xhci->shared_hcd, irq, IRQF_SHARED);
        if (ret)
                goto dealloc_usb2_hcd;

        device_enable_async_suspend(&pdev->dev);
        pm_runtime_put_noidle(&pdev->dev);

        /*
         * Prevent runtime pm from being on as default, users should enable
         * runtime pm using power/control in sysfs.
         */
        pm_runtime_forbid(&pdev->dev);

        return 0;


dealloc_usb2_hcd:
        usb_remove_hcd(hcd);

disable_usb_phy:
        usb_phy_shutdown(hcd->usb_phy);

put_usb3_hcd:
        usb_put_hcd(xhci->shared_hcd);

disable_clk:
        clk_disable_unprepare(xhci->clk);

disable_reg_clk:
        clk_disable_unprepare(xhci->reg_clk);

put_hcd:
        usb_put_hcd(hcd);

disable_runtime:
        pm_runtime_put_noidle(&pdev->dev);
        pm_runtime_disable(&pdev->dev);

        return ret;
}
```
The probe function firstly assigns the xhci_plat_hc_driver object 
to the driver local variable. 
Remember that 
xhci_plat_hc_driver object is intialized 
to contain the reference of xhci core hc_driver
at the module loading time. 


























### xHCI platform probe - registering root hub






XXXTODO!!
###Registering root hub from the controller
```c
/**
 * usb_add_hcd - finish generic HCD structure initialization and register
 * @hcd: the usb_hcd structure to initialize
 * @irqnum: Interrupt line to allocate
 * @irqflags: Interrupt type flags
 *
 * Finish the remaining parts of generic HCD initialization: allocate the
 * buffers of consistent memory, register the bus, request the IRQ line,
 * and call the driver's reset() and start() routines.
 */
int usb_add_hcd(struct usb_hcd *hcd,
                unsigned int irqnum, unsigned long irqflags)
{
        int retval;
        struct usb_device *rhdev;

        if (!hcd->skip_phy_initialization && usb_hcd_is_primary_hcd(hcd)) {
                hcd->phy_roothub = usb_phy_roothub_alloc(hcd->self.sysdev);
                if (IS_ERR(hcd->phy_roothub))
                        return PTR_ERR(hcd->phy_roothub);

                retval = usb_phy_roothub_init(hcd->phy_roothub);
                if (retval)
                        return retval;

                retval = usb_phy_roothub_set_mode(hcd->phy_roothub,
                                                  PHY_MODE_USB_HOST_SS);
                if (retval)
                        retval = usb_phy_roothub_set_mode(hcd->phy_roothub,
                                                          PHY_MODE_USB_HOST);
                if (retval)
                        goto err_usb_phy_roothub_power_on;

                retval = usb_phy_roothub_power_on(hcd->phy_roothub);
                if (retval)
                        goto err_usb_phy_roothub_power_on;
        }

        dev_info(hcd->self.controller, "%s\n", hcd->product_desc);

        switch (authorized_default) {
        case USB_AUTHORIZE_NONE:
                hcd->dev_policy = USB_DEVICE_AUTHORIZE_NONE;
                break;

        case USB_AUTHORIZE_ALL:
                hcd->dev_policy = USB_DEVICE_AUTHORIZE_ALL;
                break;

        case USB_AUTHORIZE_INTERNAL:
                hcd->dev_policy = USB_DEVICE_AUTHORIZE_INTERNAL;
                break;

        case USB_AUTHORIZE_WIRED:
        default:
                hcd->dev_policy = hcd->wireless ?
                        USB_DEVICE_AUTHORIZE_NONE : USB_DEVICE_AUTHORIZE_ALL;
                break;
        }

        set_bit(HCD_FLAG_HW_ACCESSIBLE, &hcd->flags);

        /* per default all interfaces are authorized */
        set_bit(HCD_FLAG_INTF_AUTHORIZED, &hcd->flags);

        /* HC is in reset state, but accessible.  Now do the one-time init,
         * bottom up so that hcds can customize the root hubs before hub_wq
         * starts talking to them.  (Note, bus id is assigned early too.)
         */
        retval = hcd_buffer_create(hcd);
        if (retval != 0) {
                dev_dbg(hcd->self.sysdev, "pool alloc failed\n");
                goto err_create_buf;
        }

        retval = usb_register_bus(&hcd->self);
        if (retval < 0)
                goto err_register_bus;

        rhdev = usb_alloc_dev(NULL, &hcd->self, 0);
        if (rhdev == NULL) {
                dev_err(hcd->self.sysdev, "unable to allocate root hub\n");
                retval = -ENOMEM;
                goto err_allocate_root_hub;
        }
        mutex_lock(&usb_port_peer_mutex);
        hcd->self.root_hub = rhdev;
        mutex_unlock(&usb_port_peer_mutex);

        rhdev->rx_lanes = 1;
        rhdev->tx_lanes = 1;

        switch (hcd->speed) {
        case HCD_USB11:
                rhdev->speed = USB_SPEED_FULL;
                break;
        case HCD_USB2:
                rhdev->speed = USB_SPEED_HIGH;
                break;
        case HCD_USB25:
                rhdev->speed = USB_SPEED_WIRELESS;
                break;
        case HCD_USB3:
                rhdev->speed = USB_SPEED_SUPER;
                break;
        case HCD_USB32:
                rhdev->rx_lanes = 2;
                rhdev->tx_lanes = 2;
                fallthrough;
        case HCD_USB31:
                rhdev->speed = USB_SPEED_SUPER_PLUS;
                break;
        default:
                retval = -EINVAL;
                goto err_set_rh_speed;
        }

        /* wakeup flag init defaults to "everything works" for root hubs,
         * but drivers can override it in reset() if needed, along with
         * recording the overall controller's system wakeup capability.
         */
        device_set_wakeup_capable(&rhdev->dev, 1);

        /* HCD_FLAG_RH_RUNNING doesn't matter until the root hub is
         * registered.  But since the controller can die at any time,
         * let's initialize the flag before touching the hardware.
         */
        set_bit(HCD_FLAG_RH_RUNNING, &hcd->flags);

        /* "reset" is misnamed; its role is now one-time init. the controller
         * should already have been reset (and boot firmware kicked off etc).
         */
        if (hcd->driver->reset) {
                retval = hcd->driver->reset(hcd);
                if (retval < 0) {
                        dev_err(hcd->self.controller, "can't setup: %d\n",
                                        retval);
                        goto err_hcd_driver_setup;
                }
        }
        hcd->rh_pollable = 1;

        retval = usb_phy_roothub_calibrate(hcd->phy_roothub);
        if (retval)
                goto err_hcd_driver_setup;

        /* NOTE: root hub and controller capabilities may not be the same */
        if (device_can_wakeup(hcd->self.controller)
                        && device_can_wakeup(&hcd->self.root_hub->dev))
                dev_dbg(hcd->self.controller, "supports USB remote wakeup\n");

        /* initialize tasklets */
        init_giveback_urb_bh(&hcd->high_prio_bh);
        init_giveback_urb_bh(&hcd->low_prio_bh);

        /* enable irqs just before we start the controller,
         * if the BIOS provides legacy PCI irqs.
         */
        if (usb_hcd_is_primary_hcd(hcd) && irqnum) {
                retval = usb_hcd_request_irqs(hcd, irqnum, irqflags);
                if (retval)
                        goto err_request_irq;
        }

        hcd->state = HC_STATE_RUNNING;
        retval = hcd->driver->start(hcd);
        if (retval < 0) {
                dev_err(hcd->self.controller, "startup error %d\n", retval);
                goto err_hcd_driver_start;
        }

        /* starting here, usbcore will pay attention to this root hub */
        retval = register_root_hub(hcd);
        if (retval != 0)
                goto err_register_root_hub;

        if (hcd->uses_new_polling && HCD_POLL_RH(hcd))
                usb_hcd_poll_rh_status(hcd);

        return retval;

err_register_root_hub:
        hcd->rh_pollable = 0;
        clear_bit(HCD_FLAG_POLL_RH, &hcd->flags);
        del_timer_sync(&hcd->rh_timer);
        hcd->driver->stop(hcd);
        hcd->state = HC_STATE_HALT;
        clear_bit(HCD_FLAG_POLL_RH, &hcd->flags);
        del_timer_sync(&hcd->rh_timer);
err_hcd_driver_start:
        if (usb_hcd_is_primary_hcd(hcd) && hcd->irq > 0)
                free_irq(irqnum, hcd);
err_request_irq:
err_hcd_driver_setup:
err_set_rh_speed:
        usb_put_invalidate_rhdev(hcd);
err_allocate_root_hub:
        usb_deregister_bus(&hcd->self);
err_register_bus:
        hcd_buffer_destroy(hcd);
err_create_buf:
        usb_phy_roothub_power_off(hcd->phy_roothub);
err_usb_phy_roothub_power_on:
        usb_phy_roothub_exit(hcd->phy_roothub);

        return retval;
}
EXPORT_SYMBOL_GPL(usb_add_hcd);
```



```c
/**
 * register_root_hub - called by usb_add_hcd() to register a root hub
 * @hcd: host controller for this root hub
 *
 * This function registers the root hub with the USB subsystem.  It sets up
 * the device properly in the device tree and then calls usb_new_device()
 * to register the usb device.  It also assigns the root hub's USB address
 * (always 1).
 *
 * Return: 0 if successful. A negative error code otherwise.
 */
static int register_root_hub(struct usb_hcd *hcd)
{
        struct device *parent_dev = hcd->self.controller;
        struct usb_device *usb_dev = hcd->self.root_hub;
        const int devnum = 1;
        int retval;

        usb_dev->devnum = devnum;
        usb_dev->bus->devnum_next = devnum + 1;
        set_bit (devnum, usb_dev->bus->devmap.devicemap);
        usb_set_device_state(usb_dev, USB_STATE_ADDRESS);

        mutex_lock(&usb_bus_idr_lock);

        usb_dev->ep0.desc.wMaxPacketSize = cpu_to_le16(64);
        retval = usb_get_device_descriptor(usb_dev, USB_DT_DEVICE_SIZE);
        if (retval != sizeof usb_dev->descriptor) {
                mutex_unlock(&usb_bus_idr_lock);
                dev_dbg (parent_dev, "can't read %s device descriptor %d\n",
                                dev_name(&usb_dev->dev), retval);
                return (retval < 0) ? retval : -EMSGSIZE;
        }

        if (le16_to_cpu(usb_dev->descriptor.bcdUSB) >= 0x0201) {
                retval = usb_get_bos_descriptor(usb_dev);
                if (!retval) {
                        usb_dev->lpm_capable = usb_device_supports_lpm(usb_dev);
                } else if (usb_dev->speed >= USB_SPEED_SUPER) {
                        mutex_unlock(&usb_bus_idr_lock);
                        dev_dbg(parent_dev, "can't read %s bos descriptor %d\n",
                                        dev_name(&usb_dev->dev), retval);
                        return retval;
                }
        }

        retval = usb_new_device (usb_dev);
        if (retval) {
                dev_err (parent_dev, "can't register root hub for %s, %d\n",
                                dev_name(&usb_dev->dev), retval);
        } else {
                spin_lock_irq (&hcd_root_hub_lock);
                hcd->rh_registered = 1;
                spin_unlock_irq (&hcd_root_hub_lock);

                /* Did the HC die before the root hub was registered? */
                if (HCD_DEAD(hcd))
                        usb_hc_died (hcd);      /* This time clean up */
        }
        mutex_unlock(&usb_bus_idr_lock);

        return retval;
}
```


##When xHCI platform driver can be probed???














