FROM debian:13

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get -y install mtr

ENTRYPOINT ["mtr", "-4", "-r", "-w", "-b", "-z", "48.208.184.230"]