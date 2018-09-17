#
# Run all CORE3D metrics and report results.
#

import os
import sys
import shutil
import gdalconst
import numpy as np
import argparse
import json


try:
    import core3dmetrics.geometrics as geo
except:
    import geometrics as geo


# PRIMARY FUNCTION: RUN_GEOMETRICS
def run_geometrics(configfile,refpath=None,testpath=None,outputpath=None,
    align=True,allow_test_ignore=False):

    # check inputs
    if not os.path.isfile(configfile):
        raise IOError("Configuration file does not exist")

    if outputpath is not None and not os.path.isdir(outputpath):
        raise IOError('"outputpath" not a valid folder <{}>'.format(outputpath))

    # parse configuration
    configpath = os.path.dirname(configfile)

    config = geo.parse_config(configfile,
        refpath=(refpath or configpath), 
        testpath=(testpath or configpath))

    # Get test model information from configuration file.
    testDSMFilename = config['INPUT.TEST']['DSMFilename']
    testDTMFilename = config['INPUT.TEST'].get('DTMFilename',None)
    testCLSFilename = config['INPUT.TEST']['CLSFilename']
    testMTLFilename = config['INPUT.TEST'].get('MTLFilename',None)

    # Get reference model information from configuration file.
    refDSMFilename = config['INPUT.REF']['DSMFilename']
    refDTMFilename = config['INPUT.REF']['DTMFilename']
    refCLSFilename = config['INPUT.REF']['CLSFilename']
    refNDXFilename = config['INPUT.REF']['NDXFilename']
    refMTLFilename = config['INPUT.REF'].get('MTLFilename',None)

    # Get material label names and list of material labels to ignore in evaluation.
    materialNames = config['MATERIALS.REF']['MaterialNames']
    materialIndicesToIgnore = config['MATERIALS.REF']['MaterialIndicesToIgnore']
    
    # Get plot settings from configuration file
    PLOTS_SHOW   = config['PLOTS']['ShowPlots']
    PLOTS_SAVE   = config['PLOTS']['SavePlots']
    PLOTS_ENABLE = PLOTS_SHOW or PLOTS_SAVE

    # default output path
    if outputpath is None:
        outputpath = os.path.dirname(testDSMFilename)

    # Configure plotting
    basename = os.path.basename(testDSMFilename)
    if PLOTS_ENABLE:
        plot = geo.plot(saveDir=outputpath, autoSave=PLOTS_SAVE, savePrefix=basename+'_', badColor='black',showPlots=PLOTS_SHOW, dpi=900,
            cmap='viridis')
    else:
        plot = None
        
    # copy testDSM to the output path
    # this is a workaround for the "align3d" function with currently always
    # saves new files to the same path as the testDSM
    src = testDSMFilename
    dst = os.path.join(outputpath,os.path.basename(src))
    if not os.path.isfile(dst): shutil.copyfile(src,dst)
    testDSMFilename_copy = dst

    # Register test model to ground truth reference model.
    if not align:
        print('\nSKIPPING REGISTRATION')
        xyzOffset = (0.0,0.0,0.0)
    else:
        print('\n=====REGISTRATION====='); sys.stdout.flush()
        try:
            align3d_path = config['REGEXEPATH']['Align3DPath']
        except:
            align3d_path = None
        xyzOffset = geo.align3d(refDSMFilename, testDSMFilename_copy, exec_path=align3d_path)

    # Explicitly assign a no data value to warped images to track filled pixels
    noDataValue = -9999

    # Read reference model files.
    print("\nReading reference model files...")
    refCLS, tform = geo.imageLoad(refCLSFilename)
    refDSM = geo.imageWarp(refDSMFilename, refCLSFilename, noDataValue=noDataValue)
    refDTM = geo.imageWarp(refDTMFilename, refCLSFilename, noDataValue=noDataValue)
    refNDX = geo.imageWarp(refNDXFilename, refCLSFilename, interp_method=gdalconst.GRA_NearestNeighbour).astype(np.uint16)

    if refMTLFilename:
        refMTL = geo.imageWarp(refMTLFilename, refCLSFilename, interp_method=gdalconst.GRA_NearestNeighbour).astype(np.uint8)
        refMTL[refMTL==2] = 1 # MANUALLY ADJUST CONCRETE TO COMBINED CLASS
    else:
        print('NO REFERENCE MTL')

    # Read test model files and apply XYZ offsets.
    print("\nReading test model files...")
    testCLS = geo.imageWarp(testCLSFilename, refCLSFilename, xyzOffset, gdalconst.GRA_NearestNeighbour)
    testDSM = geo.imageWarp(testDSMFilename, refCLSFilename, xyzOffset, noDataValue=noDataValue)

    if testDTMFilename:
        testDTM = geo.imageWarp(testDTMFilename, refCLSFilename, xyzOffset, noDataValue=noDataValue)
    else:
        print('NO TEST DTM: defaults to reference DTM')
        testDTM = refDTM

    if testMTLFilename:
        testMTL = geo.imageWarp(testMTLFilename, refCLSFilename, xyzOffset, gdalconst.GRA_NearestNeighbour).astype(np.uint8)
    else:
        print('NO TEST MTL')

    print("\n\n")

    # Apply registration offset, only to valid data to allow better tracking of bad data
    testValidData = (testDSM != noDataValue)
    if testDTMFilename:
        testValidData &= (testDTM != noDataValue)

    testDSM[testValidData] = testDSM[testValidData] + xyzOffset[2]
    if testDTMFilename:
        testDTM[testValidData] = testDTM[testValidData] + xyzOffset[2]

    # Create mask for ignoring points labeled NoData in reference files.
    refDSM_NoDataValue = noDataValue
    refDTM_NoDataValue = noDataValue
    refCLS_NoDataValue = geo.getNoDataValue(refCLSFilename)
    ignoreMask = np.zeros_like(refCLS, np.bool)

    if refDSM_NoDataValue is not None:
        ignoreMask[refDSM == refDSM_NoDataValue] = True
    if refDTM_NoDataValue is not None:
        ignoreMask[refDTM == refDTM_NoDataValue] = True
    if refCLS_NoDataValue is not None:
        ignoreMask[refCLS == refCLS_NoDataValue] = True

    # optionally ignore test NoDataValue(s)
    if allow_test_ignore:

        if allow_test_ignore == 1:
            testCLS_NoDataValue = geo.getNoDataValue(testCLSFilename)
            if testCLS_NoDataValue is not None:
                print('Ignoring test CLS NoDataValue')
                ignoreMask[testCLS == testCLS_NoDataValue] = True

        elif allow_test_ignore == 2:
            testDSM_NoDataValue = noDataValue
            testDTM_NoDataValue = noDataValue
            if testDSM_NoDataValue is not None:
                print('Ignoring test DSM NoDataValue')
                ignoreMask[testDSM == testDSM_NoDataValue] = True
            if testDTMFilename and testDTM_NoDataValue is not None:
                print('Ignoring test DTM NoDataValue')
                ignoreMask[testDTM == testDTM_NoDataValue] = True

        else:
            raise IOError('Unrecognized test ignore value={}'.format(allow_test_ignore))

        print("")

    # sanity check
    if np.all(ignoreMask):
        raise ValueError('All pixels are ignored')

    # report "data voids"
    numDataVoids = np.sum(ignoreMask > 0)
    print('Number of data voids in ignore mask = ', numDataVoids)

    # If quantizing to voxels, then match vertical spacing to horizontal spacing.
    QUANTIZE = config['OPTIONS']['QuantizeHeight']
    if QUANTIZE:
        unitHgt = geo.getUnitHeight(tform)
        refDSM = np.round(refDSM / unitHgt) * unitHgt
        refDTM = np.round(refDTM / unitHgt) * unitHgt
        testDSM = np.round(testDSM / unitHgt) * unitHgt
        testDTM = np.round(testDTM / unitHgt) * unitHgt
        noDataValue = np.round(noDataValue / unitHgt) * unitHgt
       
    if PLOTS_ENABLE:

        # ranges
        fac = 10
        mn = np.ceil(np.amin(refDSM[~ignoreMask])/fac) * fac
        mx = np.floor(np.amax(refDSM[~ignoreMask])/fac) * fac

        # mn = 240
        # mx = 300
        dsm_range = [mn,mx]



        # Reference models can include data voids, so ignore invalid data on display
        plot.make(refDSM, 'Reference DSM', 111, colorbar=True, saveName="input_refDSM", badValue=noDataValue,
            vmin=dsm_range[0],vmax=dsm_range[1])
        plot.make(refDTM, 'Reference DTM', 112, colorbar=True, saveName="input_refDTM", badValue=noDataValue,
            vmin=dsm_range[0],vmax=dsm_range[1])
        plot.make(refCLS, 'Reference Classification', 113,  colorbar=True, saveName="input_refClass")

        # plot.make(refMask, 'Reference Evaluation Mask', 114, colorbar=True, saveName="input_refMask",
        #     cmap='gray',vmin=0,vmax=1)

        # Test models shouldn't have any invalid data
        # so display the invalid values to highlight them,
        # unlike with the refSDM/refDTM
        plot.make(testDSM, 'Test DSM', 151, colorbar=True, saveName="input_testDSM",
            vmin=dsm_range[0],vmax=dsm_range[1])
        plot.make(testDTM, 'Test DTM', 152, colorbar=True, saveName="input_testDTM",
            vmin=dsm_range[0],vmax=dsm_range[1])
        plot.make(testCLS, 'Test Classification', 153, colorbar=True, saveName="input_testClass")

        # plot.make(testMask, 'Test Evaluation Mask', 154, colorbar=True, saveName="input_testMask",
        #     cmap='gray',vmin=0,vmax=1)

        plot.make(ignoreMask, 'Ignore Mask', 181, colorbar=True, saveName="input_ignoreMask",
            cmap='gray',vmin=0,vmax=1)

        plot.make(testValidData, 'Test Valid Mask', 182, colorbar=True, saveName="input_testValidMask",
            cmap='gray',vmin=0,vmax=1)

        # material maps
        if refMTLFilename and testMTLFilename:
            (mtl_index,mtl_name,mtl_color) = geo.material_map()
            plot.make(refMTL, 'Reference Materials', 191, colorbar=True, saveName="input_refMTL",
                vmin=min(mtl_index)-0.5,vmax=max(mtl_index)+0.5,
                cmap=mtl_color,cm_ticks=mtl_index,cm_labels=mtl_name,cm_invert=True)
            plot.make(testMTL, 'Test Materials', 192, colorbar=True, saveName="input_testMTL",
                vmin=min(mtl_index)-0.5,vmax=max(mtl_index)+0.5,
                cmap=mtl_color,cm_ticks=mtl_index,cm_labels=mtl_name,cm_invert=True)

            temp = np.copy(refMTL)
            temp[refNDX==0] = 0
            plot.make(temp, 'Reference Materials Masked', 192, colorbar=True, saveName="input_refMTLmasked",
                vmin=min(mtl_index)-0.5,vmax=max(mtl_index)+0.5,
                cmap=mtl_color,cm_ticks=mtl_index,cm_labels=mtl_name,cm_invert=True)

            temp = np.copy(testMTL)
            temp[refNDX==0] = 0
            for k in config['MATERIALS.REF']['MaterialIndicesToIgnore']: temp[refMTL==k] = 0
            plot.make(temp, 'Test Materials Masked', 192, colorbar=True, saveName="input_testMTLmasked",
                vmin=min(mtl_index)-0.5,vmax=max(mtl_index)+0.5,
                cmap=mtl_color,cm_ticks=mtl_index,cm_labels=mtl_name,cm_invert=True)
        # # material maps
        # if refMTLFilename and testMTLFilename:
        #     plot.make(refMTL, 'Reference Materials', 191, colorbar=True, saveName="input_refMTL",vmin=0,vmax=13)
        #     plot.make(testMTL, 'Test Materials', 192, colorbar=True, saveName="input_testMTL",vmin=0,vmax=13)

    # Run the threshold geometry metrics and report results.
    metrics = dict()

    # Run threshold geometry and relative accuracy
    threshold_geometry_results = []
    relative_accuracy_results = []
    
    # Check that match values are valid
    refCLS_matchSets, testCLS_matchSets = geo.getMatchValueSets(config['INPUT.REF']['CLSMatchValue'], config['INPUT.TEST']['CLSMatchValue'], np.unique(refCLS).tolist(), np.unique(testCLS).tolist())

    if PLOTS_ENABLE:
        # Update plot prefix include counter to be unique for each set of CLS value evaluated
        original_save_prefix = plot.savePrefix

    # Loop through sets of CLS match values
    for index, (refMatchValue,testMatchValue) in enumerate(zip(refCLS_matchSets,testCLS_matchSets)):
        print("Evaluating CLS values")
        print("  Reference match values: " + str(refMatchValue))
        print("  Test match values: " + str(testMatchValue))

        # object masks based on CLSMatchValue(s)
        refMask = np.zeros_like(refCLS, np.bool)
        for v in refMatchValue:
            refMask[refCLS == v] = True

        testMask = np.zeros_like(testCLS, np.bool)
        if len(testMatchValue):
            for v in testMatchValue:
                testMask[testCLS == v] = True

        if PLOTS_ENABLE:
            plot.savePrefix = original_save_prefix + "%03d"%(index) + "_"
            plot.make(testMask, 'Test Evaluation Mask', 154, colorbar=True, saveName="input_testMask",
                cmap='gray',vmin=0,vmax=1)
            plot.make(refMask, 'Reference Evaluation Mask', 114, colorbar=True, saveName="input_refMask",
                cmap='gray',vmin=0,vmax=1)

        # Evaluate threshold geometry metrics using refDTM as the testDTM to mitigate effects of terrain modeling uncertainty
        result = geo.run_threshold_geometry_metrics(refDSM, refDTM, refMask, testDSM, refDTM, testMask, tform, ignoreMask, plot=plot)
        if refMatchValue == testMatchValue:
            result['CLSValue'] = refMatchValue
        else:
            result['CLSValue'] = {'Ref': refMatchValue, "Test": testMatchValue}
        threshold_geometry_results.append(result)

        # Run the relative accuracy metrics and report results.
        # Skip relative accuracy is all of testMask or refMask is assigned as "object"
        if not ((refMask.size == np.count_nonzero(refMask)) or (testMask.size == np.count_nonzero(testMask))) and len(testMatchValue) != 0:
            result = geo.run_relative_accuracy_metrics(refDSM, testDSM, refMask, testMask, ignoreMask, geo.getUnitWidth(tform), plot=plot)
            if refMatchValue == testMatchValue:
                result['CLSValue'] = refMatchValue
            else:
                result['CLSValue'] = {'Ref': refMatchValue, "Test": testMatchValue}
            relative_accuracy_results.append(result)

    if PLOTS_ENABLE:
        # Reset plot prefix
        plot.savePrefix = original_save_prefix

    metrics['threshold_geometry'] = threshold_geometry_results
    metrics['relative_accuracy'] = relative_accuracy_results

    if align:
        metrics['registration_offset'] = xyzOffset

    # Run the terrain model metrics and report results.
    if testDTMFilename:
        dtm_z_threshold = config['OPTIONS'].get('TerrainZErrorThreshold',1)

        # Make reference mask for terrain evaluation that identified elevated object where underlying terrain estimate
        # is expected to be inaccurate
        dtm_CLS_ignore_values = config['INPUT.REF'].get('TerrainCLSIgnoreValues', [6, 17]) # Default to building and bridge deck
        dtm_CLS_ignore_values = geo.validateMatchValues(dtm_CLS_ignore_values,np.unique(refCLS).tolist())
        refMaskTerrainAcc = np.zeros_like(refCLS, np.bool)
        for v in dtm_CLS_ignore_values:
            refMaskTerrainAcc[refCLS == v] = True

        metrics['terrain_accuracy'] = geo.run_terrain_accuracy_metrics(refDTM, testDTM, refMaskTerrainAcc, dtm_z_threshold, plot=plot)
    else:
        print('WARNING: No test DTM file, skipping terrain accuracy metrics')

    # Run the threshold material metrics and report results.
    if testMTLFilename:
        metrics['threshold_materials'] = geo.run_material_metrics(refNDX, refMTL, testMTL, materialNames, materialIndicesToIgnore)
    else:
        print('WARNING: No test MTL file, skipping material metrics')

    fileout = os.path.join(outputpath,os.path.basename(configfile) + "_metrics.json")
    with open(fileout,'w') as fid:
        json.dump(metrics,fid,indent=2)
    print(json.dumps(metrics,indent=2))
    print("Metrics report: " + fileout)

    #  If displaying figures, wait for user before existing
    if PLOTS_SHOW:
            input("Press Enter to continue...")

# command line function
def main(args=None):
    if args is None:
        args = sys.argv[1:]

    # parse inputs
    parser = argparse.ArgumentParser(description='core3dmetrics entry point', prog='core3dmetrics')

    parser.add_argument('-c', '--config', dest='config',
                        help='Configuration file', required=True, metavar='')
    parser.add_argument('-r', '--reference', dest='refpath',
                        help='Reference data folder', required=False, metavar='')
    parser.add_argument('-t', '--test', dest='testpath',
                        help='Test data folder', required=False, metavar='')
    parser.add_argument('-o', '--output', dest='outputpath',
                        help='Output folder', required=False, metavar='')
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument('--align', dest='align', action='store_true', help="Enable alignment (default)")
    group.add_argument('--no-align', dest='align', action='store_false', help="Disable alignment")
    group.set_defaults(align=True)

    # optional argument
    # note if "--test-ignore" specified without argument, testignore==1
    parser.add_argument('--test-ignore', dest='testignore',
        help="Ignore test NoDataValue(s) (0=off, 1=ignore CLS, 2=ignore DSM/DTM",
        required=False, nargs='?', default=0, const=1, 
        choices=range(0,3), type=int, metavar='')

    args = parser.parse_args(args)

    print('RUN_GEOMETRICS input arguments:')
    print(args)

    # gather optional arguments
    kwargs = {}
    kwargs['align'] = args.align
    if args.refpath: kwargs['refpath'] = args.refpath
    if args.testpath: kwargs['testpath'] = args.testpath
    if args.outputpath: kwargs['outputpath'] = args.outputpath
    if args.testignore: kwargs['allow_test_ignore'] = args.testignore

    # run process
    run_geometrics(configfile=args.config,**kwargs)

if __name__ == "__main__":
    main()

