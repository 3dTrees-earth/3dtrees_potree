# PotreeConverter patches

Applied during Docker build after cloning PotreeConverter 2.1.1.

- **duplicate_attributes_keep.patch**  
  Stops dropping extra dimensions that share a name with a standard attribute (e.g. a second `classification` in the VLR). Naming:
  - If a dimension name occurs **once**, it is left unchanged.
  - If it occurs **multiple times**, the first is `name_1`, the second `name_2`, etc.
  So byte offsets stay correct and each attribute has its own output slot (no overwrites).

- **chunker_classification_lookup.patch**  
  Generalised fix: when `duplicate_attributes_keep.patch` renames a standard LAS attribute
  (e.g. `classification` → `classification_1`), the chunker's hardcoded lookups would miss it
  (returning offset -1 / nullptr → `inf` min/max). This patch:
  1. Adds a **fallback** in `Attributes::get()` / `getOffset()`: if `name` is not found, also
     try `name_1` (covers every renamed standard attribute automatically).
  2. After building the standard-handler mapping, **generates aliases** for any output attribute
     whose name ends in `_N` and whose base name has an existing handler
     (e.g. `classification_1` → same handler as `classification`).
