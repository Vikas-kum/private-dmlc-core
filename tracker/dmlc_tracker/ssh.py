#!/usr/bin/env python
"""
DMLC submission script by ssh

One need to make sure all slaves machines are ssh-able.
"""
from __future__ import absolute_import

from multiprocessing import Pool, Process
import os, subprocess, logging
from threading import Thread
from . import tracker

def sync_dir(local_dir, slave_node, slave_dir):
    """
    sync the working directory from root node into slave node
    """
    remote = slave_node[0] + ':' + slave_dir
    logging.info('rsync %s -> %s', local_dir, remote)
    prog = 'rsync -az --rsh="ssh -o StrictHostKeyChecking=no -p %s" %s %s' % (
        slave_node[1], local_dir, remote)
    subprocess.check_call([prog], shell = True)

def get_env(pass_envs):
    envs = []
    # get system envs
    keys = ['OMP_NUM_THREADS', 'KMP_AFFINITY', 'LD_LIBRARY_PATH', 'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY', 'DMLC_INTERFACE']
    for k in keys:
        v = os.getenv(k)
        if v is not None:
            envs.append('export ' + k + '=' + v + ';')
    # get ass_envs
    for k, v in pass_envs.items():
        envs.append('export ' + str(k) + '=' + str(v) + ';')
    return (' '.join(envs))

def launch_new_worker_node(args):
    pass_envs = {}
    if args.launch_worker is True:
        pass_envs['DMLC_ROLE'] = 'worker'
        pass_envs['DMLC_NODE_HOST'] = args.host
        pass_envs['ELASTIC_TRAINING_ENABLED']= '1'

        if args.env is not None:
            for entry in args.env:
                entry = entry.strip()
                i = entry.find(":")
                if i != -1:
                    val = entry[i+1:]
                    pass_envs[entry[:i]] = val
    
        prog = get_env(pass_envs) +  (' '.join(args.command))
        port = 22
        if args.port is not None:
            port = args.port

        prog = 'ssh -A -o StrictHostKeyChecking=no ' + args.host + ' -p ' + port + ' \'' + prog + '\''
        logging.info("Launching new worker jobs :{} env:{}".format( prog, os.environ))
        thread = Thread(target = lambda: subprocess.check_call(prog, env=os.environ, shell=True), args=() )
        thread.setDaemon(True)
        thread.start()
        thread.join(10)
        return

def submit(args):
    if args.launch_worker is True:
      launch_new_worker_node(args)
      return
    assert args.host_file is not None
    with open(args.host_file) as f:
        tmp = f.readlines()
    assert len(tmp) > 0
    hosts=[]
    for h in tmp:
        if len(h.strip()) > 0:
            # parse addresses of the form ip:port
            h = h.strip()
            i = h.find(":")
            p = "22"
            if i != -1:
                p = h[i+1:]
                h = h[:i]
            # hosts now contain the pair ip, port
            hosts.append((h, p))
    
    if args.elastic_training_enabled is True:
        # create worker host file
        if os.path.exists(args.worker_host_file):
            os.remove(args.worker_host_file)
        with open(args.worker_host_file, 'a') as whf:
            for i in range(args.num_workers + args.num_servers):
                if i >= args.num_servers:
                    (node, port) = hosts[i % len(hosts)]
                    whf.write(node + "\n")
        if os.path.exists(args.worker_host_file + "_log"):
            os.remove(args.worker_host_file + "_log")
        f = open(args.worker_host_file + "_log", "w+")
        f.close()

        
    def ssh_submit(nworker, nserver, pass_envs):
        """
        customized submit script
        """
        # thread func to run the job
        def run(prog):
            subprocess.check_call(prog, shell = True)

        # sync programs if necessary
        local_dir = os.getcwd()+'/'
        working_dir = local_dir
        if args.sync_dst_dir is not None and args.sync_dst_dir != 'None':
            working_dir = args.sync_dst_dir
            pool = Pool(processes=len(hosts))
            for h in hosts:
                pool.apply_async(sync_dir, args=(local_dir, h, working_dir))
            pool.close()
            pool.join()
            

        # launch jobs
        for i in range(nworker + nserver):
            pass_envs['DMLC_ROLE'] = 'server' if i < nserver else 'worker'
            (node, port) = hosts[i % len(hosts)]
            pass_envs['DMLC_NODE_HOST'] = node
            if args.elastic_training_enabled:
                pass_envs['ELASTIC_TRAINING_ENABLED']= '1' 
            prog = get_env(pass_envs) + ' cd ' + working_dir + '; ' + (' '.join(args.command))
            prog = 'ssh -o StrictHostKeyChecking=no ' + node + ' -p ' + port + ' \'' + prog + '\''
            thread = Thread(target = run, args=(prog,))
            thread.setDaemon(True)
            thread.start()

        return ssh_submit
    logging.info("cmd:%s", args.command)
    tracker.submit(args.num_workers, args.num_servers,
                   fun_submit=ssh_submit,
                   pscmd=(' '.join(args.command)),
                   hostIP=args.host_ip, args=args)
