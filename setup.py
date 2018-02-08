#!/usr/local/bin/python3

import csv
import logging
import itertools
import json
import multiprocessing
import os
import pydub 
import tempfile
import threading
import time
import random
import youtube_dl


class AudioDataGatherer(object):
    ''' builds a directory full of useful audio clips from Google's audioset '''
    
    def __init__(this,  audioset_file, ontology_file, log_level = logging.WARN):

        this.log = logging.getLogger( type(this).__name__)
        this.log.setLevel(log_level)

        this.log.info ("Created")

        this.log.info('opening ontology json: ' + str(ontology_file))
        this.ontol = open(ontology_file).read()
        this.ontol = json.loads(this.ontol)
        
        this.log.info('opening audioset csv: ' + str(audioset_file))
        this.audset = open(audioset_file)

        # the first few lines are not relivant
        this.log.debug( 'skipping: ' + str(this.audset.readline() ))
        this.log.debug( 'skipping: ' + str(this.audset.readline() ))
        this.log.debug( 'skipping: ' + str(this.audset.readline() ))

        this.audset= list(csv.DictReader(this.audset.readlines(), 
                        fieldnames=[ 'YTID', 'start_seconds', 'end_seconds', 'positive_labels'],
                        delimiter=',',
                        quotechar='"',
                        quoting = csv.QUOTE_ALL,
                        skipinitialspace=True))

    def build(this, include_names=[], exclude_names=[], output_dir = None, max_clips=None, 
                max_threads = 1):
        

        this.log.debug('Building with includes:' + str(include_names) + 
                        ' or exclude: ' + str(exclude_names) )

        include_names, exclude_names = this._cludes_sanity(
                                            include_names, exclude_names)

        output_dir = this._setup_dir(output_dir)

        if len(include_names) > 0: 
            labels = this._getIDbyNames( include_names ) 
            metas = this._includeClipsByLabels(labels, max_clips)
        else: 
            labels = this._getIDbyNames( exclude_names ) 
            metas = this._excludeClipsByLabels(labels, max_clips)

        this.log.info('collected ' + str(len(metas)) + ' metadatas')
   
        if max_threads == 1:
            this.log.info('Single Threaded Clip Gatherer')
            this._gather_st( metas, output_dir)
        else:
            this.log.info('Multi Threaded Clip Gatherer')
            this._gather_mt(metas, output_dir, max_threads)

    #
    #
    #
    def _gather_st(this, metas, data_dir):
        ''' Single threaded meta gatherer '''
        
        this.log.debug('Single Threaded Clip Gatherer')

        for meta in metas:
            cid, cstart, cend  = meta
            this.log.debug('Gathering clip: ' + str(cid) + 
                            ' s: ' + str(cstart) + ' e:' + str(cend))

            this._build_ytid(
                    ytid=cid, start=cstart, stop=cend, data_dir=data_dir)
        

        this.log.info('Gathering complete!')


    #
    #
    #
    def _gather_mt(this, metas, data_dir, max_threads):
        ''' Multi threaded meta gatherer '''

        this.log.debug('Multi Threaded Clip Gatherer')

        threads = []

        for meta in metas:                
            
            #stop if thread limited
            while len(threads) >= max_threads:
                threads = list(filter( lambda x: x.exitcode == None, threads))
                if len(threads) >= max_threads: time.sleep(0.1)
               
            #t = threading.Thread(
            t = multiprocessing.Process(
                        target=this._gather_st, \
                        kwargs = dict(metas=[meta], data_dir=data_dir))

            this.log.debug('Launching Thread for: ' + str(meta[0]))
            t.start()
            threads.append(t)

        this.log.debug('Waiting for last threads to finish')
        threads = list(filter( lambda x: x.exitcode == None, threads))
        for t in threads:
            t.join()

        this.log.info('Gathering complete!')

    #
    #
    #
    def _setup_dir(this, ddir=None):
        ''' setup an output directory if necessary ''' 
        ddir = ddir if ddir is not None else os.getcwd()

        if not os.path.exists(ddir):
            this.log.debug('Creating data directory: ' + str(ddir))
            os.makedirs(ddir)

        return ddir           

    #
    #
    #
    def _cludes_sanity( this, include, exclude):
        ''' does some simple sanity checking on the includes + excludes '''

        if isinstance(include, str): include = [ include ]
        if isinstance(exclude, str): exclude = [ exclude ]

        assert( ( len(include) > 0 and len(exclude) == 0 )  or 
                ( len(include) == 0 and len(exclude) > 0) ) 
        
        return include, exclude




    def _getIDbyNames(this, names):
        ''' selects ontology ID's by their corresponding human readable names '''
        
        this.log.debug('Selecting Ontology ID by NAME(S): ' + str(names))

        if isinstance(names, str): names = [ names ]

        subs = [ x for x in this.ontol if x['name'] in names ]
        
        return [ x['id'] for x in subs ]


    def _includeClipsByLabels( this, labels, max_clips=None):
        ''' returns a number of (youtubeID, start_time, end_time) tuples 
            for a given set of labels  
        '''
        assert( len(labels) > 0 ) 
        
        this.log.debug('Searching for ' + str(labels) )

        clips = []

        for row in this.audset:
            for label in labels:

                if label in row['positive_labels']: 
                    
                    #this.log.debug('Adding: ' + str(row))
                    clips.append( (row['YTID'],row['start_seconds'],row['end_seconds'] ) )

        if max_clips!=None and len(clips) >= max_clips:
            this.log.info('Excessive number of clips found (' 
                                + str(len(clips)) + '), downsampling')
            clips = this._downsample(clips, max_clips)

        this.log.info('Total Clips : ' + str(len(clips)))

        return clips                        

    def _excludeClipsByLabels( this, labels, max_clips=None):
        ''' returns a number of (youtubeID, start_time, end_time) tuples 
            excluding any with a given set of labels  
        '''
        assert( len(labels) > 0 ) 
        
        this.log.debug('Removing clips with ' + str(labels) )

        clips = []

        for row in this.audset:

            for label in labels:
                if label in row['positive_labels']: 
                    this.log.debug('EXCLUDING : ' + str(row))
                    continue  # skip the row

            #this.log.debug('Adding: ' + str(row))
            clips.append( (row['YTID'],row['start_seconds'],row['end_seconds'] ) )

        if max_clips!=None and len(clips) >= max_clips:
            this.log.info('Excessive number of clips found (' 
                                + str(len(clips)) + '), downsampling')
            clips = this._downsample(clips, max_clips)

        this.log.info('Total Clips : ' + str(len(clips)))

        return clips                        

 

            

    def _downsample(this, data, nsamples):
        
        subset = random.sample(list(data), nsamples)
        return subset
        

    def _build_ytid(this, ytid, data_dir, start=0.0, stop=None):
        '''
            Gets a youtube video based on youtube id, pulls out
            the audio between start and stop, and saves it to the data
            directory
        '''
         
        ddir = data_dir 

        this.log.info('Downloading' + str(ytid) )
        this.log.debug('\t\t' + ' into ' + str(ddir))

        fname = ddir + '/' + ytid + '.wav'

        if os.path.exists(fname):
            this.log.info('File already exists: ' + str(fname) + ' skipping')

        else: 
            origwd = os.getcwd()
            with tempfile.TemporaryDirectory( 
                        suffix=str(threading.get_ident())) as tmpdir:
                os.chdir(tmpdir)
            
                tmpname = this._download_ytid(ytid)
                if tmpname != None:
                    this._crop( tmpname, fname, start, stop)

            os.chdir(origwd)

    def _crop(this, in_fname, out_fname, start=0, stop=None): 
        ''' 
        Crops a wave file on disk, overwrites the current file
        '''

        this.log.info('cropping : ' + str(in_fname) )
        
        orig_aud = pydub.AudioSegment.from_wav(in_fname)

        if isinstance(start, str): start = int(float(start))
        start_ms = int(start * 1000)

        if stop:
            if isinstance(stop, str): stop= int(float(stop))
            stop_ms = int(stop * 1000)
            new_aud = orig_aud[start_ms:stop_ms]
        else:
            new_aud = orig_aud[start_ms:]
        
        this.log.debug('writing to: ' + str(out_fname))
        new_aud.export(out_fname)
        

    def _download_ytid(this, ytid):
        '''
        Downloads a youtube video, extracts wav audio
        NOTE:  downloads to current working directory, so chdir first!
        '''
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '%(id)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
            }],
            'logger': this.log,
            #'progress_hooks': [my_hook],
        }

        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            url = 'https://www.youtube.com/watch?v=' + str(ytid)
            this.log.info("Downloading YTID: " + str(ytid) + ' : ' + str(url))
            try:
                ydl.download([url] )
            except youtube_dl.utils.DownloadError as e:
                this.log.warn('Video not found, skipping ' + str(ytid))
                return None

        return os.getcwd() + '/' + ytid + '.wav'


if __name__ == '__main__':
    
    logging.basicConfig ( level = logging.WARN,
                        format='%(levelname)s [0x%(process)x] %(name)s: %(message)s')
   

    #data_dir = os.getcwd() + '/_data'
    #yte = YoutubeExtractor()
    #yte.get('FLcqHUR58AU', data_dir, start=5000, stop=9000)

    #j = OntologyParser('./ontology/ontology.json')
    #z = j.getIDbyNames( ['Truck'] )
    #print (z)
    #z = j.getIDbyNames( ['Truck', 'Engine'] )
    #print (z)

    #s = AudioMetadataGatherer('balanced_train_segments.csv')
    #z = s.getClipsByLabels('/m/07r04',10) # Truck
    #print (z[0:2])
    #s.getClipsByLabels(z) # Truck
    #s.getClipsByLabels(z[0], 10) # Truck
    
    #make our random a little less random
    random.seed(42)
    
    #good data
    good_dir = os.getcwd() + '/_data/good'
    a = AudioDataGatherer(audioset_file = 'balanced_train_segments.csv', 
                            ontology_file = './ontology/ontology.json', 
                            log_level = logging.INFO)
    a.build( include_names=['Truck','Engine'], output_dir=good_dir, max_clips = 5000, 
                max_threads = 50)

    bad_dir = os.getcwd() + '/_data/bad'
    a.build( exclude_names=['Truck','Engine'], output_dir=bad_dir, max_clips = 5000,
                max_threads = 50)

