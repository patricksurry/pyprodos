This project uses uv and a virtual env in .venv/

After activating the venv you can run tests with pytest ...  You can also run the CLI tool using prodos ...

The project emulates the Apple // ProDOS filesystem
and its data structures so those must remain compatible with ProDOS disk images.  This spec is useful background https://prodos8.com/docs/techref/file-organization/ 

The source files are in src/prodos with a simple
CLI defined in src/p8cli.  
The CLI should not implement complex logic, that should remain in the core files.  
The key source files are device.py which implements a BlockDevice which reads and writes
the blocks defined in blocks.py.
It includes an access log to watch how the higher level routines are using the device.  
The ProDOS volume is defined in volume.py.
There are helpers to manage files and directories in file.py and directory.py.

