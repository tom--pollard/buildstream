kind: autotools
variables:
  result: "Nothing"
  (?):
  - machine_arch == "aarch32":
      result: "Army"
  - machine_arch == "aarch64":
      result: "Aarchy"
