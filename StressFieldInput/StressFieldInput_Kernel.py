import abaqus
import numpy as np
import traceback
from MeshElementCategory import MeshElementCategory
from MeshElementData import MeshElementData


# Main method which runs the code
def run_plugin(default_job, stress_scale_counts, stress_scale_min, stress_scale_max,
               stress_script, error_script, run_jobs, iterate):
    # Feedback message
    print('=== STRESS INPUT START ===')
    # Run checks
    if run_checks(default_job, stress_scale_counts, stress_scale_min, stress_scale_max, stress_script):
        # Characterize the mesh
        mesh_data = characterize_mesh(default_job, stress_script)
        # Do not continue if there is no mesh
        if mesh_data is None:
            print_exit_message()
            return
        # Calculate the stresses
        mesh_data = define_stresses(mesh_data, stress_script)
        if mesh_data is None:
            print_exit_message()
            return
        # Build the jobs for the stress fields
        jobs = create_jobs(default_job, mesh_data, stress_scale_counts, stress_scale_min, stress_scale_max)
        # Run the jobs
        if run_jobs:
            errors = execute_jobs(jobs, error_script, iterate)
            print(errors)
    # Feedback message
    print_exit_message()


# Prints the end feedback message
def print_exit_message():
    print('=== STRESS INPUT FINISHED ===')


# Method checking if all prerequisites are met before running the code
def run_checks(default_job, stress_scale_counts, stress_scale_min, stress_scale_max, stress_script):
    # Feedback message
    print('> Performing checks')
    print('-> Checking inputs and MDB')
    # Check for the number of stress scales
    if stress_scale_counts < 1:
        print('-> Number of stress scales should be larger than 0')
        return False
    # Check for the stress scale bounds
    if stress_scale_max < stress_scale_min:
        print('-> Minimum stress scale should be smaller or equal to the maximum stress scale')
        return False
    # Check for weird stress scale definitions
    if (stress_scale_max > stress_scale_min) and stress_scale_counts == 1:
        print('-> Unclear stress scale definition, only one count for different min and max')
        return False
    if (stress_scale_max == stress_scale_min) and stress_scale_counts > 1:
        print('-> Unclear stress scale definition, multiple counts for equal min and max')
        return False
    # Check if there is an active model
    if len(abaqus.mdb.models.keys()) <= 0:
        print('-> No active model')
        return False
    # Check if there is a default job
    if default_job == '':
        print('-> No default job')
        return False
    # Check if the default job has a model
    job = abaqus.mdb.jobs[default_job]
    if not hasattr(job, 'model'):
        print('-> Invalid job, job does not have an associated model')
        return False
    # Check if the default job is valid
    if default_job not in abaqus.mdb.jobs.keys():
        print('-> Invalid default job')
        return False
    # Attempt to run the stress script
    if not check_stress_script(stress_script):
        print('-> Stress script invalid')
        return False
    # All checks passed
    print('-> Checks passed')
    return True


# Method to check if the stress script has been properly defined
def check_stress_script(stress_script):
    # Feedback message
    print('-> Checking stress script')
    # Try to run the script
    try:
        execfile(stress_script, globals())
    except Exception:
        # If it fails, return
        print('--> Stress script threw an error')
        print(traceback.format_exc())
        return False
    # Check now if the stress calculation method exists
    if 'calculate_stress' not in globals().keys():
        print('--> Function "calculate_stress" not defined in stress script')
        return False
    # Check if the method is callable
    func = globals()['calculate_stress']
    if not callable(func):
        print('--> Function "calculate_stress" not callable in stress script')
        return False
    # Check the method arguments
    import inspect
    args = inspect.getargspec(func)
    if len(args) != 4:
        print('--> Invalid arguments for "calculate_stress"; should have precisely 4: "part", "x", "y", and "z".')
    return True


# Method to characterize the mesh
def characterize_mesh(default_job, stress_script):
    # Feedback message
    print("> Characterizing mesh")
    # Run the stress script to enable access to the get_category() method at the current level
    categorize = True
    try:
        execfile(stress_script, globals())  # Pass in globals() to load the script's contents to the global dictionary
    except Exception:
        # If it fails, don't categorize
        categorize = False
    # Check if the categorization function is implemented
    if categorize:
        categorize = 'get_category' in globals().keys()
        if categorize:
            func = globals()['get_category']
            categorize = callable(func)
            if categorize:
                print('-> Function "get_category" detected in stress script')
    # Fetch the job
    job = abaqus.mdb.jobs[default_job]
    # Fetch the model from the job
    model = job.model
    if isinstance(model, basestring) or isinstance(model, str):
        # Note that according to the documentation, model can be a Model object or a String with the model name
        model = abaqus.mdb.models[model]
    # Fetch the instances in the assembly
    instances = model.rootAssembly.allInstances
    instance_count = len(instances.keys())
    # Log element data for each of the instances
    mesh_data = np.empty(instance_count, dtype=object)
    no_mesh = True
    # Iterate over the part instances
    for instance_index in np.arange(0, instance_count):
        # Fetch instance properties
        instance_key = instances.keys()[instance_index]
        instance = instances[instance_key]
        part_name = instance.part.name
        elements = instance.elements
        element_count = len(elements)
        if element_count > 0:
            # Toggle the flag
            no_mesh = False
            # Create mesh categories
            part_mesh_data = {}
            for element_index in np.arange(0, element_count):
                # Fetch the element
                element = elements[element_index]
                # fetch the label
                label = element.label
                # fetch the centre coordinates
                x = 0
                y = 0
                z = 0
                node_count = len(element.getNodes())
                for node in element.getNodes():
                    coordinates = node.coordinates
                    x = x + coordinates[0]
                    y = y + coordinates[1]
                    z = z + coordinates[2]
                x = (x + 0.0) / node_count
                y = (y + 0.0) / node_count
                z = (z + 0.0) / node_count
                # create a new mesh element data object
                element_data = MeshElementData(instance_key, part_name, label, x, y, z)
                # Identify the category
                if categorize:
                    try:
                        category = get_category(part_name, x, y, z)
                    except Exception:
                        # If categorization script fails, cancel
                        print('-> Function "get_category" failed for element ' + element.get_label() + ', aborting')
                        print(traceback.format_exc())
                        return None
                else:
                    category = element_data.get_label()
                # Store the mesh element
                if category in part_mesh_data.keys():
                    part_mesh_data[category].add_element(element_data)
                else:
                    part_mesh_data[category] = MeshElementCategory(category, element_data)
            # Store the categories
            mesh_data[instance_index] = part_mesh_data
        else:
            # Store None
            mesh_data[instance_index] = None
    if no_mesh:
        print('-> No mesh present, aborting')
        return None
    return mesh_data


# Method to define the stress data
def define_stresses(mesh_data, stress_script):
    # Run the script to enable access to the calculate_stress() method at the current level
    try:
        execfile(stress_script, globals())  # Pass in globals() to load the script's contents to the global dictionary
    except Exception:
        # If it fails, return None
        print('---> Stress script threw an error')
        print(traceback.format_exc())
        return None
    # Iterate over part instances
    for part_index in np.arange(0, len(mesh_data)):
        part_mesh_data = mesh_data[part_index]
        if part_mesh_data is None:
            continue
        # Iterate over mesh element categories
        for category_key in part_mesh_data.keys():
            # Fetch the category
            mesh_category = part_mesh_data[category_key]
            # Fetch the element
            element = mesh_category.get_first_element()
            # Calculate the stress (method will be available from the stress script)
            try:
                stress = calculate_stress(element.get_part_name(), element.get_x(), element.get_y(), element.get_z())
            except Exception:
                # If stress script fails, default to zero
                print('---> Stress script threw an error during calculation for element ' + mesh_category.get_id())
                print(traceback.format_exc())
                stress = [0, 0, 0, 0, 0, 0]
            # Define the stress
            mesh_category.define_stress(stress)
    return mesh_data


# Method to handle reading and writing of input files
def create_jobs(default_job, mesh_data, stress_scale_counts, stress_scale_min, stress_scale_max):
    # Feedback message
    print('> Generating input files')
    # Fetch the job
    job = abaqus.mdb.jobs[default_job]
    # Write the default input file
    job.writeInput()
    # Read the default input and inject the element sets
    default_input, line_index = inject_element_sets(mesh_data, read_lines_from_file(job.name + '.inp'))
    # Find the line at which to inject stress fields
    line_index, predefined = find_stress_injection_line(default_input, line_index)
    # Inject the stresses and create jobs
    jobs = [None] * stress_scale_counts
    # Run code for each stress scale count
    for i in np.arange(0, stress_scale_counts):
        if stress_scale_counts == 1:
            stress_scale = stress_scale_min
        else:
            stress_scale = stress_scale_min + (i + 0.0)*(stress_scale_max - stress_scale_min)/(stress_scale_counts - 1)
        print('---> Creating job for stress factor ' + str(stress_scale))
        # Generate input file
        input_file = inject_stress_field(mesh_data, stress_scale, default_input, line_index, predefined)
        # Generate the job
        jobs[i] = abaqus.mdb.JobFromInputFile(default_job + '_Stress_Input_Scale_' + str(i + 1), input_file)
    # Return the jobs
    return jobs


# Method to inject element set definitions into an existing input file
def inject_element_sets(mesh_data, default_input):
    next_line = 0
    sets_to_inject = np.arange(0, len(mesh_data))
    current_part_index = -1
    while True:
        # fetch the current line
        line = default_input[next_line]
        # increment line index
        next_line = next_line + 1
        # check if the current mode is set injection or part scanning
        if current_part_index < 0:
            # check if the line starts a part definition
            if line[:12] == '*Part, name=':
                current_part = line[12:]
            else:
                continue
            # part definition reached, iterate over the remaining parts to inject
            print('-> Found input file part definition for ' + current_part)
            set_index = 0
            while set_index < len(sets_to_inject):
                part_element_categories = mesh_data[sets_to_inject[set_index]]
                if part_element_categories is None or len(part_element_categories) <= 0:
                    # this part has no data to inject, remove it from the parts to inject index list
                    sets_to_inject = np.delete(sets_to_inject, set_index)
                else:
                    # fetch a single category
                    part_element_category = part_element_categories[part_element_categories.keys()[0]]
                    # this part has data to inject, check if it is the current part in the input file
                    if part_element_category.get_part_name() == current_part:
                        # it is the current part in the input file, set as current part being injected
                        current_part_index = sets_to_inject[set_index]
                        print('--> Injecting sets for part ' + part_element_category.get_part_name())
                        # also remove it from the parts to inject index list
                        sets_to_inject = np.delete(sets_to_inject, set_index)
                        # increment the current line as it will be '*Node'
                        next_line = next_line + 1
                        break
                    else:
                        # this is a different part, leave it in the list and move to the next index
                        set_index = set_index + 1
            if current_part_index < 0:
                print('--> Skipping ' + current_part)
        # current mode is set injection
        else:
            # if the line starts with a space, continue
            if line[0] == ' ':
                continue
            # if the line starts with an asterisk, a new section is found
            if line[0] == '*':
                # the next section is an element definition section
                if line[:15] == '*Element, type=':
                    continue
                # set injection point has been reached
                else:
                    # Inject the element sets
                    print('--> Element set injection starts at line: ' + str(next_line))
                    part_element_categories = mesh_data[current_part_index]
                    # Decrement next line once
                    next_line = next_line - 1
                    # Do the actual injection
                    for category_key in part_element_categories.keys():
                        # Fetch the category
                        element_category = part_element_categories[category_key]
                        # Insert element set definition
                        default_input[next_line:next_line] = ['*Elset, elset=' + element_category.get_set_name()]
                        next_line = next_line + 1
                        # Fetch the elements
                        elements = element_category.get_elements()
                        # Write the elements
                        line = ''
                        element_counter = 0
                        element_limit = 8
                        for i in np.arange(0, len(elements)):
                            # Fetch next element
                            element = elements[i]
                            # Add the element to the line
                            line = line + str(element.get_label()) + ','
                            element_counter = element_counter + 1
                            if element_counter == element_limit or i >= (len(elements) - 1):
                                # Write the line
                                default_input[next_line:next_line] = [line]
                                next_line = next_line + 1
                                # Reset the line and counter
                                line = ''
                                element_counter = 0
                            else:
                                line = line + ' '
                    # Reset the current part index
                    current_part_index = -1
                    # Re-increment the next line
                    next_line = next_line + 1
            # if the line does not start with a space or asterisk, it is element definition and to be skipped
            else:
                continue
        # check if set injection is complete
        if len(sets_to_inject) <= 0:
            # only break from the while loop if the last part is actually injected
            if current_part_index < 0:
                break
    return default_input, next_line


# Method to find the line at which to inject stresses
def find_stress_injection_line(default_input, next_line):
    bc_section_index = -1
    inject_index = -1
    predefined_fields_present = False
    while True:
        # fetch the current line
        line = default_input[next_line]
        # Increment the line index
        next_line = next_line + 1
        # If the BC section has not yet been found, check for it
        if bc_section_index < 0:
            if line == '** BOUNDARY CONDITIONS':
                bc_section_index = next_line - 1
        # If the BC section has been found, find where it ends
        else:
            if line == '** PREDEFINED FIELDS':
                predefined_fields_present = True
                continue
            if line[0:4] == '** -':
                inject_index = next_line - 1
                break
    print('--> Stress field injection starts at line: ' + str(inject_index + 1))
    return inject_index, predefined_fields_present


# Method to inject a stress field in the input file and generate a job for it
def inject_stress_field(mesh_data, stress_scale, default_input, inject_index, predefined_fields_present):
    # Create a copy of the default input
    lines = default_input
    # Put in the header for the predefined field
    if not predefined_fields_present:
        lines[inject_index:inject_index] = ['** ']
        inject_index = inject_index + 1
        lines[inject_index:inject_index] = ['** PREDEFINED FIELDS']
        inject_index = inject_index + 1
        lines[inject_index:inject_index] = ['** ']
        inject_index = inject_index + 1
    lines[inject_index:inject_index] = ['*Initial Conditions, type=STRESS']
    inject_index = inject_index + 1
    # Iterate over part instances
    for part_index in np.arange(0, len(mesh_data)):
        part_mesh_data = mesh_data[part_index]
        if part_mesh_data is None:
            continue
        # Iterate over the mesh element categories
        for category_key in part_mesh_data.keys():
            # fetch the category
            mesh_category = part_mesh_data[category_key]
            # Fetch the stress
            stress = mesh_category.get_stress()
            # Scale the stress
            stress = stress_scale * stress
            # Inject in the input file
            line = mesh_category.get_instance_name() + '.' + mesh_category.get_set_name() + ','
            for stress_index in np.arange(0, len(stress)):
                line = line + str(stress[stress_index]) + ','
            lines[inject_index:inject_index] = [line]
    # Write the input file
    input_file_name = 'stress_input_scale_' + str(stress_scale) + '.inp'
    out = open(input_file_name, 'w')
    for line_index in np.arange(0, len(default_input)):
        out.write(default_input[line_index] + '\n')
    out.close()
    return input_file_name


# Method to run the jobs
def execute_jobs(jobs, error_script, iterate):
    # todo: error iterations
    # Run the jobs
    print('> Running jobs')
    for i in np.arange(0, len(jobs)):
        print('-> Running job ' + str(i + 1) + ' of ' + str(len(jobs)))
        jobs[i].submit()
        jobs[i].waitForCompletion()
    # Check if an error script exists
    if error_script is None or error_script == '':
        return []
    # Run the script to enable access to the calculate_error() method at the current level
    print('> Calculating Errors')
    try:
        execfile(error_script, globals())  # Pass in globals() to load the script's contents to the global dictionary
    except Exception:
        # If it fails, return
        print('-> Error script threw an error')
        print(traceback.format_exc())
        return []
    # Calculate the errors
    errors = np.zeros(len(jobs))
    for i in np.arange(0, len(jobs)):
        # Feedback message
        print('-> Calculating error for job ' + str(i + 1) + ' of ' + str(len(jobs)))
        # open the ODB
        odb = abaqus.session.openOdb(jobs[i].name + ".odb", readOnly=True)
        # Calculate the error (method will be available from the error script)
        try:
            errors[i] = calculate_error(abaqus.session, odb)
        except Exception:
            # If an error script fails, return
            print('---> Error script threw an error during calculation')
            print(traceback.format_exc())
            return []
    # Return the errors
    return errors


# utility method to read lines from file
def read_lines_from_file(file_name):
    # read the file contents
    fid = open(file_name, 'r')
    raw = fid.read().strip()
    fid.close()
    return raw.split('\n')


# Utility method to inspect an object and print its attributes and methods to the console
def inspect_object(obj):
    import inspect
    members = inspect.getmembers(obj)
    for member in members:
        print('---------------------')
        print(str(member))
    print('---------------------')
