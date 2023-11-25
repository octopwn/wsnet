# wsnet
A lightweight protocol implementation to perform TCP and authentication proxying over websockets.  
It's actually Layer3 agnostic, but websockets was easy to use.

# If you are here for the OctoPwn

## Install
Either use PIP `pip install wsnet` or clone + install via GitHub.

## Starting server
After installing you should have a new binary called `wsnet-wssserver`.  
By default the server generates its own certificate and private key because Firefox doesn't allow mixed content on localhost, but it is allowed in Chrome. This behaviour can be disabled by using the `--plaintext` switch.  
By default this server generates a random path which is used to protect the server agains potential malicious JS from other pages trying to use the server. This can be disabled by `--disable-security`, but this also disables the `Origin` header check which is part of the same protection mechanism.  

If you wish to run it on localhost without any security (it's your life) use the following: `wsnet-wssserver --plaintext --disable-security`

# If you are here to see what this is
Sorry, for the time being you'll need to read the code.
