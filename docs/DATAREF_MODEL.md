# DataRef Model

The system supports two complementary DataRef paths:

1. Managed DataRefs — an XPPython3 extension for plugin authors  
2. Auto‑Created DataRefs — a headless‑only fallback for sim‑less execution  

These paths never conflict and serve different purposes.

-------------------------------------------------------------------------------

# Managed DataRefs (XPPython3 extension for production plugins)

Managed DataRefs are declared by plugin authors using DataRefSpec and DataRefManager.  
They define the plugin’s contract with X‑Plane and provide a structured, production‑grade way to describe all DataRefs a plugin depends on.

### Benefits for production plugins

• Strong typing (FLOAT, INT, FLOAT_ARRAY, BYTE_ARRAY, etc.)  
• Required vs optional semantics  
• Defaults used until X‑Plane provides real values  
• Automatic waiting for required DataRefs during startup  
• Deterministic array shape inferred from default lists  
• Unified, type‑safe accessor API  
• Clean separation between plugin logic and xp.* calls  

### Binding lifecycle (performed once in `ready()`)

When the plugin calls `manager.ready()`:

1. Every declared DataRefSpec is bound exactly once  
2. A handle is obtained (real or placeholder)  
3. Metadata is captured (type, writable, array size)  
4. A typed accessor is created  
5. Required DataRefs must have real handles before `ready()` returns True  
6. Optional DataRefs may remain placeholders indefinitely  

After this binding step, all managed DataRefs use stable handles for the lifetime of the plugin.

### Required DataRefs

A DataRefSpec marked `required=True` indicates that the plugin depends on this DataRef being present in X‑Plane.

Until X‑Plane provides the real value, the plugin receives:

• A placeholder handle  
• Zero‑initialized values  
• Full read/write capability  

Once X‑Plane exposes the real DataRef, the plugin transitions seamlessly.

### Optional DataRefs

A DataRefSpec marked `required=False` allows the plugin to operate even if the DataRef never appears.  
Defaults remain in effect for the lifetime of the plugin.

### Manager Access API

The DataRefManager exposes a clean, unified API for plugin authors:

• `manager.get(path_or_enum)` — returns the typed accessor  
• `manager.set(path_or_enum, value)` — convenience setter for simple scalars  
• `manager.has(path_or_enum)` — check if a spec exists  
• `manager.all_paths()` — enumerate declared DataRefs  
• `manager.ready()` — perform binding and check required DataRefs  

Typed accessors expose:

• `.get()` / `.set(value)` for scalars  
• `.getv()` / `.setv(list)` for arrays  
• `.size` for array length  
• `.dtype` for declared type  

This keeps plugin code clean, explicit, and production‑safe.

-------------------------------------------------------------------------------

# Auto‑Created DataRefs (headless‑only fallback)

When running outside X‑Plane, plugins may reference DataRefs that normally come from the simulator.

If a plugin calls `findDataRef()` on a path **not declared** in DataRefManager:

A DataRef is created automatically using deterministic inference.

This feature exists **only for headless development and testing**.  
It is **not** a production feature and should not be relied on inside X‑Plane.

### Inference rules

• If the path ends with “s” or contains “array”:  
  – Type = FLOAT_ARRAY  
  – Size = 8  
  – Value = [0.0] * 8  

• Otherwise:  
  – Type = FLOAT  
  – Value = 0.0  

### Managed overrides

If a path exists in DataRefManager, the managed spec always wins.  
Auto‑creation never overrides plugin‑declared DataRefs.

-------------------------------------------------------------------------------

# Unified Access Layer

Regardless of origin (managed or auto‑created), all DataRefs are accessed through the standard xp.* API:

• findDataRef  
• getDataf / setDataf  
• getDatai / setDatai  
• getDatavf / setDatavf  
• getDatab / setDatab  
• getDataRefInfo  
