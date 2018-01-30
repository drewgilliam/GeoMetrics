#
# Run all CORE3D metrics and report results.
#

import os
import sys
import shutil
import configparser
import gdal, gdalconst
import numpy as np
import geometrics as geo
import argparse
import json
import glob


# HELPER: LOCATE ABSOLUTE FILE PATH with GLOB
def findfiles(data,path=None):

    for key,file in data.items():
        if not key.lower().endswith('filename'): continue

        print('\nSearching for "{}"'.format(key))

        # absolute path to file
        if not os.path.isabs(file):
            if path: file = os.path.join(path,file)
            file = os.path.abspath(file)

        # locate file (use glob to allow wildcards)
        files = glob.glob(file)

        if not files:
            print("WARNING: unable to locate file <{}>".format(file))
            file = None
        else:
            if len(files) > 1:
                print('WARNING: multiple files located for <{}>, using 1st file'.format(file))

            file = files[0]
            print('File located <{}>'.format(file))

        # save file to data
        data[key] = file

    return data


# PRIMARY FUNCTION: RUN_GEOMETRICS
def run_geometrics(configfile=None,refpath=None,testpath=None,outputpath=None):

    # current absolute path of this function
    curpath = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))

    # parse configuration
    config = geo.process_config(configfile=configfile,
        refpath=(refpath or curpath), testpath=(testpath or curpath))

    # check inputs
    if outputpath is not None and not os.path.isdir(outputpath):
        raise IOError('"outputpath" not a valid folder <{}>'.format(outputpath))

    # Get test model information from configuration file.
    testDSMFilename = config['INPUT.TEST']['DSMFilename']
    testDTMFilename = config['INPUT.TEST']['DTMFilename']
    testCLSFilename = config['INPUT.TEST']['CLSFilename']
    testMTLFilename = config['INPUT.TEST']['MTLFilename']
    TEST_CLS_VALUE = config['INPUT.TEST']['CLSMatchValue']

    # Get reference model information from configuration file.
    refDSMFilename = config['INPUT.REF']['DSMFilename']
    refDTMFilename = config['INPUT.REF']['DTMFilename']
    refCLSFilename = config['INPUT.REF']['CLSFilename']
    refNDXFilename = config['INPUT.REF']['NDXFilename']
    refMTLFilename = config['INPUT.REF']['MTLFilename']
    REF_CLS_VALUE = config['INPUT.REF']['CLSMatchValue']

    # Get material label names and list of material labels to ignore in evaluation.
    materialNames = config['MATERIALS.REF']['MaterialNames']
    materialIndicesToIgnore = config['MATERIALS.REF']['MaterialIndicesToIgnore']

    # default output path
    if outputpath is None:
        outputpath = os.path.dirname(testDSMFilename)

    # copy testDSM to the output path
    # this is a workaround for the "align3d" function with currently always
    # saves new files to the same path as the testDSM
    src = testDSMFilename
    dst = os.path.join(outputpath,os.path.basename(src))
    if not os.path.isfile(dst): shutil.copyfile(src,dst)
    testDSMFilename_copy = dst

    # Register test model to ground truth reference model.
    print('\n=====REGISTRATION====='); sys.stdout.flush()
    xyzOffset = geo.align3d(refDSMFilename, testDSMFilename_copy)

    # Read reference model files.
    print("")
    print("Reading reference model files...")
    refMask, tform = geo.imageLoad(refCLSFilename)
    refDSM = geo.imageWarp(refDSMFilename, refCLSFilename)
    refDTM = geo.imageWarp(refDTMFilename, refCLSFilename)
    refNDX = geo.imageWarp(refNDXFilename, refCLSFilename, interp_method=gdalconst.GRA_NearestNeighbour).astype(np.uint16)
    refMTL = geo.imageWarp(refMTLFilename, refCLSFilename, interp_method=gdalconst.GRA_NearestNeighbour).astype(np.uint8)

    # Read test model files and apply XYZ offsets.
    print("Reading test model files...")
    print("")

    testMask = geo.imageWarp(testCLSFilename, refCLSFilename, xyzOffset, gdalconst.GRA_NearestNeighbour)
    testDSM = geo.imageWarp(testDSMFilename, refCLSFilename, xyzOffset)
    testDSM = testDSM + xyzOffset[2]

    if testDTMFilename is None:
        print('WARNING: no test DTM, using reference DTM')
        testDTM = refDTM
    else:
        testDTM = geo.imageWarp(testDTMFilename, refCLSFilename, xyzOffset)
        testDSM = testDSM + xyzOffset[2]

    if testMTLFilename is None:
        testMTL = None        
    else:
        testMTL = geo.imageWarp(testMTLFilename, refCLSFilename, xyzOffset, gdalconst.GRA_NearestNeighbour).astype(np.uint8)

    # Create mask for ignoring points labeled NoData in reference files.
    refDSM_NoDataValue = geo.getNoDataValue(refDSMFilename)
    refDTM_NoDataValue = geo.getNoDataValue(refDTMFilename)
    refCLS_NoDataValue = geo.getNoDataValue(refCLSFilename)
    ignoreMask = np.zeros_like(refMask, np.bool)

    if refDSM_NoDataValue is not None:
        ignoreMask[refDSM == refDSM_NoDataValue] = True
    if refDTM_NoDataValue is not None:
        ignoreMask[refDTM == refDTM_NoDataValue] = True
    if refCLS_NoDataValue is not None:
        ignoreMask[refMask == refCLS_NoDataValue] = True

    # If quantizing to voxels, then match vertical spacing to horizontal spacing.
    QUANTIZE = config['OPTIONS']['QuantizeHeight']
    if QUANTIZE:
        unitHgt = (np.abs(tform[1]) + abs(tform[5])) / 2
        refDSM = np.round(refDSM / unitHgt) * unitHgt
        refDTM = np.round(refDTM / unitHgt) * unitHgt
        testDSM = np.round(testDSM / unitHgt) * unitHgt
        testDTM = np.round(testDTM / unitHgt) * unitHgt

    # Run the threshold geometry metrics and report results.
    metrics = geo.run_threshold_geometry_metrics(refDSM, refDTM, refMask, REF_CLS_VALUE, testDSM, testDTM, testMask, TEST_CLS_VALUE,
                                       tform, ignoreMask)

    metrics['offset'] = xyzOffset
    
    fileout = os.path.join(outputpath,os.path.basename(testDSMFilename) + "_metrics.json")
    with open(fileout,'w') as fid:
        json.dump(metrics,fid,indent=2)
    print(json.dumps(metrics,indent=2))

    # Run the threshold material metrics and report results.
    if testMTL is None:
        print('WARNING: no test material, skipping material metrics')
    else:
        geo.run_material_metrics(refNDX, refMTL, testMTL, materialNames, materialIndicesToIgnore)


# command line function
def main():

  # parse inputs
  parser = argparse.ArgumentParser()
  parser.add_argument('-c', '--config', dest='config', 
      help='Configuration file', required=False)
  parser.add_argument('-r', '--reference', dest='refpath', 
      help='Reference data folder', required=False)
  parser.add_argument('-t', '--test', dest='testpath', 
      help='Test data folder', required=False)
  parser.add_argument('-o', '--output', dest='outputpath', 
      help='Output folder', required=False)
  
  args = parser.parse_args()

  # gather optional arguments
  kwargs = {}
  if args.config: kwargs['configfile'] = args.config
  if args.refpath: kwargs['refpath'] = args.refpath
  if args.testpath: kwargs['testpath'] = args.testpath
  if args.outputpath: kwargs['outputpath'] = args.outputpath

  # run process
  run_geometrics(**kwargs)


if __name__ == "__main__":
  main()

