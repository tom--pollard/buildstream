kind: autotools
description: Autotools test

depends:
- base.bst

sources:
- kind: tar
  url: project_dir:/files/amhello.tar.gz
  ref: 9ba123fa4e660929e9a0aa99f0c487b7eee59c5e7594f3284d015640b90f5590

config:

  configure-commands:
    - |
      %{autogen}
    - |
      %{configure}
    - |
      date +%s > config-time

  build-commands:
    - |
      %{make}
    - |
      date +%s > build-time
