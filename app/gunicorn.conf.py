import os
bind = '0.0.0.0:' + os.environ.get('PORT','10000')
workers = 1
threads = 4
timeout = 90
# Never record OAuth query strings or credentials in HTTP access logs.
accesslog = None
errorlog = '-'
loglevel = 'warning'
