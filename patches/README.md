# PotreeConverter patches

Applied during Docker build after cloning PotreeConverter 2.1.1.

- **duplicate_attributes_keep.patch**  
  Stops dropping extra dimensions that share a name with a standard attribute (e.g. a second `classification` in the VLR). Naming:
  - If a dimension name occurs **once** in a file, it is left unchanged.
  - If it occurs **multiple times** in a file, the first is `name_1`, the second `name_2`, etc.
  So byte offsets stay correct and each attribute has its own output slot (no overwrites).
  Names are compared within one file. The same name in another input file is the same attribute,
  so 25 input files keep a one-file point layout.

- **chunker_classification_lookup.patch**  
  Generalised fix: when `duplicate_attributes_keep.patch` renames a standard LAS attribute
  (e.g. `classification` → `classification_1`), the chunker's hardcoded lookups would miss it
  (returning offset -1 / nullptr → `inf` min/max). This patch:
  1. Adds a **fallback** in `Attributes::get()` / `getOffset()`: if `name` is not found, also
     try `name_1` (covers every renamed standard attribute automatically).
  2. After building the standard-handler mapping, **generates aliases** for any output attribute
     whose name ends in `_N` and whose base name has an existing handler
     (e.g. `classification_1` → same handler as `classification`).

- **chunker_numthreads.patch**  
  The chunker's thread counts are namespace-scope variables, initialised before `main()` applies
  `--numthreads`. This patch reads them again in `doChunking`, so the option also caps chunking.

- **laszip_64bit_point_index.patch**  
  The bundled LASzip truncates seek targets to 32 bits and sums variable chunk sizes (COPC) in a
  32-bit table. Above 2^32 points the sum wraps, the chunk search lands in the wrong chunk and the
  reader decompresses from there. This patch keeps seek targets and chunk totals in 64 bits.

- **sampler_poisson.patch**  
  `SamplerPoisson` keeps accepted points in a per-thread buffer of 1M entries and writes past its end
  when a node accepts more, which corrupts the heap (exit -11 on dataset 1484). Dense volumes reach
  that count because a node's sample spacing does not depend on point density. The buffer now grows.
  The accept test compared each candidate with up to 10,000 accepted points one by one and accepted it
  when that cap was reached, or wrongly near the node centre. It now looks up accepted points in a grid
  of spacing-sized cells, which is exact and much faster on dense data (1484: 98 to 25 min).

- **indexer_parallel_chunk_roots.patch**  
  After all chunks are indexed, PotreeConverter samples the chunk roots and the levels above them on
  one thread. On dense volumes this tail dominates the run (1484 took over 3 h 50 min and had not
  finished). Chunk-root batches are separate subtrees and nodes of one level are independent, so both
  now run on all threads. Chunk-root point sums are 64-bit.

- **chunker_count_xyz_only.patch**  
  The counting pass only needs coordinates. For LAS 1.4 point formats (COPC, layered compression)
  LASzip can skip decoding the other fields. On 2585's merged COPC, counting takes 231 s instead of
  394 s, with identical chunks. LAS 1.2 input is unaffected.

- **instance_coloring.patch**  
  Adds `--instance-coloring <table>` (repeatable). The table names an instance attribute, the
  uint16 attribute to add and the ground id, then lists instance id and colour id pairs. The
  converter fills the new attribute while it distributes points, so `--special-coloring` no longer
  writes a recoloured copy of the input that the converter then decodes twice.
