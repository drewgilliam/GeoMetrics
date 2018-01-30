# PROCESS GEOMETRICS CONFIGURATION FILE

import os
import configparser
import json
import glob
import collections
import jsonschema
import pkg_resources

# module/package name
resource_package = __name__


# HELPER: Update nested dictionary (python3 only)
def deep_update(d, overrides):
  for k, v in overrides.items():
    if isinstance(v, collections.Mapping):
      d[k] = deep_update(d.get(k, {}), v)
    else:
      d[k] = v
  return d


# HELPER: Locate absolute file path in dict via GLOB
def findfiles(data,path=None):

  for key,file in data.items():
    if not key.lower().endswith('filename'): continue

    print('Searching for "{}"'.format(key))

    if file is None:
      print('  No file specified'); continue

    # absolute path to file
    if not os.path.isabs(file):
        if path: file = os.path.join(path,file)
        file = os.path.abspath(file)

    # locate file (use glob to allow wildcards)
    files = glob.glob(file)

    if not files:
      print("  WARNING: unable to locate file <{}>".format(file))
      file = None
    else:
      if len(files) > 1:
        print('  WARNING: multiple files located for <{}>, using 1st file'.format(file))

      file = files[0]
      print('  File located <{}>'.format(file))

    # save file to data
    data[key] = file

  return data


# PROCESS CONFIGURATION FILE
def process_config(configfile=None,refpath=None,testpath=None):

  print('\n=====CONFIGURATION=====')

  # check inputs
  if configfile and not os.path.isfile(configfile):
    raise IOError("Configuration file does not exist")

  if refpath and not os.path.isdir(refpath):
    raise IOError('"refpath" not a valid folder <{}>'.format(refpath))

  if testpath and not os.path.isdir(refpath):
    raise IOError('"testpath" not a valid folder <{}>'.format(testpath))

  # load resources
  config = json.loads(pkg_resources.resource_string(
      resource_package, 'config_default.json'))
  schema = json.loads(pkg_resources.resource_string(
      resource_package, 'config_schema.json'))

  # create schema validator object (& check schema itself)
  jsonschema.Draft4Validator({}).check_schema(schema)
  validator = jsonschema.Draft4Validator(schema)

  # load user configuration
  if not configfile:
    print('\nUsing default configuration')

  else:

    print("\nReading configuration from <{}>".format(configfile))

    # JSON parsing
    if configfile.endswith(('.json','.JSON')):

      # open & read JSON file
      with open(configfile,'r') as fid:
        data = json.load(fid)

    # CONFIG parsing
    elif configfile.endswith(('.config','.CONFIG')):

      # setup config parser
      parser = configparser.ConfigParser()
      parser.optionxform = str # maintain case-sensitive items

      # read entire configuration file into dict
      if len(parser.read(configfile)) == 0:
        raise IOError("Unable to read selected .config file")
      data = {s:dict(parser.items(s)) for s in parser.sections()}   

      # special section/item parsing
      s = 'INPUT.TEST'; i = 'CLSMatchValue'; data[s][i] = [int(v) for v in data[s][i].split(',')]
      s = 'INPUT.REF'; i = 'CLSMatchValue'; data[s][i] = [int(v) for v in data[s][i].split(',')]
      s = 'OPTIONS'; i = 'QuantizeHeight'; data[s][i] = bool(data[s][i])
      s = 'PLOTS';  i = 'DoPlots'; data[s][i] = bool(data[s][i])
      s = 'MATERIALS.REF'; i = 'MaterialNames'; data[s][i] = data[s][i].split(',')
      s = 'MATERIALS.REF'; i = 'MaterialIndicesToIgnore'; data[s][i] = [int(v) for v in data[s][i].split(',')]

    # unrecognized config file type
    else:
      raise IOError('Unrecognized configuration file')

    # update default configuration with user provided options
    config = deep_update(config, data)


  # locate files for each "xxxFilename" configuration parameter
  # this makes use of "refpath" and "testpath" arguments for relative filenames
  # we do this before validation to ensure required files are located
  for item in [('INPUT.REF',refpath),('INPUT.TEST',testpath)]:
    sec = item[0]; path = item[1]
    print('\nPROCESSING "{}" FILES'.format(sec))
    config[sec] = findfiles(config[sec],path)


  # validate final configuration against schema
  try:
    validator.validate(config)
    print('\nCONFIGURATION VALIDATED')

  except jsonschema.exceptions.ValidationError:
    print('\n*****INVALID CONFIGURATION FILE*****\n')
    for error in sorted(validator.iter_errors(config), key=str):
      print('ERROR: {}\n'.format(error))

    # print()
    raise jsonschema.exceptions.ValidationError('validation error')

  
  # for easier explotation, ensure some configuration options are tuple/list
  opts = (('INPUT.TEST','CLSMatchValue'),('INPUT.REF','CLSMatchValue'),
      ('MATERIALS.REF','MaterialIndicesToIgnore'))

  for opt in opts:
    s = opt[0]; i = opt[1];
    if not isinstance(config[s][i],(tuple,list)):
      config[s][i] = [config[s][i]]


  # print final configuration
  print('\nFINAL CONFIGURATION')
  print(json.dumps(config,indent=2))

  # cleanup
  return config
  