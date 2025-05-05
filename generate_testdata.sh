#!/bin/bash

ffmpeg -f lavfi -i testsrc=size=1920x1080:rate=60 -t 3 -pix_fmt yuv420p testdata/test.y4m