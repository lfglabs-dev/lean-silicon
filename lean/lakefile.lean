import Lake
open Lake DSL

package «leanvm-b-mincore» where
  version := v!"0.1.0"

lean_lib LeanVMBMinCore where
  globs := #[.submodules `LeanVMBMinCore]

@[default_target]
lean_lib LeanVMBMinCoreRoot where
  roots := #[`LeanVMBMinCore]
