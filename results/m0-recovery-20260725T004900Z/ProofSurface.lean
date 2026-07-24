import LeanVMBMinCore.GF8
import LeanVMBMinCore.GHASH128
import LeanVMBMinCore.Memory
import LeanVMBMinCore.ISA

#print axioms LeanVMBMinCore.GF8.serialMul_correct
#print axioms LeanVMBMinCore.GF8.serialMul_zero_right
#print axioms LeanVMBMinCore.GF8.serialMul_one_right
#print axioms LeanVMBMinCore.GHASH128.xtime_xor_linear
#print axioms LeanVMBMinCore.Memory.writeOnce_conflict
#print axioms LeanVMBMinCore.ISA.hardwareStep_refines
