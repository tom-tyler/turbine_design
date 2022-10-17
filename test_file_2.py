from signal import set_wakeup_fd
from dd_turb_design import fit_data
import pandas as pd
from sklearn.gaussian_process import kernels
import matplotlib.pyplot as plt
import numpy as np

training_file_path = 'Data-Driven-Aerodynamic-Turbine-Design\data-B for training.csv'
training_data = pd.read_csv(training_file_path, 
                            names=["phi", "psi", "Lambda", "M", "Co", "eta_lost"]
                            )

testing_file_path = 'Data-Driven-Aerodynamic-Turbine-Design\data-A for testing.csv'
testing_data = pd.read_csv(testing_file_path, 
                           names=["phi", "psi", "Lambda", "M", "Co", "eta_lost"]
                           )

matern_kernel = kernels.Matern(length_scale = (1,1,1,1,1),
                         length_scale_bounds=(1e-2,1e2),
                         nu=1.5
                         )

constant_kernel_1 = kernels.ConstantKernel(constant_value=1,
                                           constant_value_bounds=(1e-6,1e1)
                                           )

constant_kernel_2 = kernels.ConstantKernel(constant_value=1,
                                           constant_value_bounds=(1e-6,1e1)
                                           )

kernel = constant_kernel_1 * matern_kernel + constant_kernel_2

fit = fit_data(kernel_form=kernel,
            training_dataframe=training_data,
            CI_percent=20,
            number_of_restarts=20)

fit.plot_grid_vars('Lambda',
                   'psi',
                   'phi',
                   [0.5,0.7,0.9,1.1],
                   'M',
                   [0.6,0.7],
                   'Co',
                   0.6,
                   num_points=500
                   )