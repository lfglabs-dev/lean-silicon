# Toolchain capture

Provisioning commands run on Ubuntu Noble:

```sh
apt-get update
apt-get install -y --no-install-recommends iverilog yosys boolector elan make python3-yaml z3 cvc5
elan toolchain install leanprover/lean4:v4.32.1
elan default leanprover/lean4:v4.32.1
git clone https://github.com/YosysHQ/SymbiYosys.git /tmp/SymbiYosys
git -C /tmp/SymbiYosys checkout --detach 45e46efad1880bb79e50a3a48183ff29a2c5a9cb
make -C /tmp/SymbiYosys install PREFIX=/usr/local
```

The SymbiYosys tag resolves to source commit `11fd202`; `sby --version` is
`SBY v0.59`. Exact discovered versions are in `versions.log`.

The executable result is `status.tsv`: `make check`, `make sim`, Lean build,
and both Yosys runs pass; bounded `sby` receives exit 124 after 45 seconds.
