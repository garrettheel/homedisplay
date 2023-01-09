# homedisplay

http://web.mta.info/developers/developer-data-terms.html#data

## Installation

First, build rpi-rgb-led-matrix in the venv

```bash
# install necessary libs
apt-get install python3-dev python3-venv git libopenjp2-7-dev python3-pillow -y

# clone lib
git clone https://github.com/hzeller/rpi-rgb-led-matrix.git

# activate venv if necessary...

# build
cd rpi-rgb-led-matrix
make build-python PYTHON=$(command -v python3)
sudo make install-python PYTHON=$(command -v python3)
```


## Usage

```bash
export MTA_API_KEY=<api_key>
export OPENWEATHER_API_KEY=<api_key>
python display.py
```
