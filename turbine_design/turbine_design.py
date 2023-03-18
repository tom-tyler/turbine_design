from sklearn.gaussian_process import GaussianProcessRegressor, kernels
from sklearn.metrics import mean_squared_error
import numpy as np
import pandas as pd
import scipy.stats as st
import matplotlib.pyplot as plt
import matplotlib.colors as mcol
from collections import OrderedDict
import sys
import joblib
from . import compflow_native as compflow
import json


def drop_columns(df,variables,output_key):
   for dataframe_variable in df.columns:
      if (dataframe_variable in variables) or (dataframe_variable==output_key):
         pass
      else:
         df=df.drop(columns=str(dataframe_variable))
   return df

class turbine_GPR: 
   
   def __init__(self,
                model_name=None,
                limit_dict='auto'):
      
      if model_name==None:
         pass
      else:   
         with open(f"turbine_design/Models/{model_name}_variables.txt", "r") as file:
            variables = [line.rstrip() for line in file]

         self.variables = variables
         self.output_key = model_name
         self.fit_dimensions = len(self.variables)
         
         model = joblib.load(f'turbine_design/Models/{model_name}_model.joblib')
         
         self.input_array_train = pd.DataFrame(data=model.X_train_,
                                               columns=sorted(self.variables))
         
         self.output_array_train = model.y_train_
         
         if limit_dict=='auto':
            self.limit_dict = {}
            for column in self.input_array_train:
               self.limit_dict[column] = (np.around(self.input_array_train[column].min(),decimals=1),
                                          np.around(self.input_array_train[column].max(),decimals=1)
                                          )
         else:
            self.limit_dict = limit_dict
            
         self.optimised_kernel = model.kernel_
         
         self.fitted_function = model
            
         self.min_train_output = np.min([self.output_array_train])
         self.max_train_output = np.max([self.output_array_train])
   
   def fit(self,
           training_dataframe,
           variables=None,
           output_key=None,
           number_of_restarts=0,           
           length_bounds=[1e-1,1e3],
           noise_magnitude=1e-6,
           noise_bounds=[1e-20,1e-3],
           nu='optimise',
           extra_variable_options=False,
           iterate_extra_params=False,
           limit_dict='auto',
           overwrite=False
           ):
      
      if variables==None:
         sys.exit('Please state variable to fit over.')
      elif output_key==None:
         sys.exit('Please state output to fit to.')
      
      self.output_key = output_key
      variables = list(variables)
      self.variables = variables
      self.fit_dimensions = len(self.variables)
      
      noise_kernel = kernels.WhiteKernel(noise_level=noise_magnitude,
                                         noise_level_bounds=noise_bounds)

      kernel_form = self.matern_kernel(len(variables),bounds=length_bounds) + noise_kernel
            
      training_dataframe = drop_columns(training_dataframe,
                                        variables,
                                        output_key)
      
      training_dataframe = training_dataframe.reindex(sorted(training_dataframe.columns), axis=1)
      
      self.input_array_train = training_dataframe.drop(columns=[self.output_key])
      self.output_array_train = training_dataframe[self.output_key]
      
      if limit_dict=='auto':
         self.limit_dict = {}
         for column in self.input_array_train:
            self.limit_dict[column] = (np.around(training_dataframe[column].min(),decimals=1),
                                       np.around(training_dataframe[column].max(),decimals=1)
                                       )
      else:
         self.limit_dict = limit_dict
      
      nu_dict = {1.5:None,2.5:None,np.inf:None}
      
      gaussian_process = GaussianProcessRegressor(kernel=kernel_form,
                                                  n_restarts_optimizer=number_of_restarts,
                                                  random_state=0
                                                  )
   
      if nu=='optimise':
         for nui in nu_dict:
            gaussian_process.set_params(kernel__k1__nu=nui)
            fitted_function = gaussian_process.fit(self.input_array_train.to_numpy(),
                                                   self.output_array_train.to_numpy()
                                                   )
            nu_dict[nui] = fitted_function.log_marginal_likelihood_value_

         nu = max(nu_dict, key=nu_dict.get)

      gaussian_process.set_params(kernel__k1__nu=nu)

      self.fitted_function = gaussian_process.fit(self.input_array_train.to_numpy(),
                                                  self.output_array_train.to_numpy()
                                                  )
         
      self.optimised_kernel = self.fitted_function.kernel_
         
      self.min_train_output = np.min([self.output_array_train])
      self.max_train_output = np.max([self.output_array_train])
      
      if overwrite==True:
         joblib.dump(self.fitted_function,f'Models/{self.output_key}_model.joblib')

         model_variables = variables.copy()
         text_model_variables = [str(item)+'\n' for item in model_variables]

         with open(f"Models/{self.output_key}_variables.txt", "w") as file:
            file.writelines(text_model_variables)

   def predict(self,
               dataframe,
               include_output=False,
               CI_in_dataframe=False,
               CI_percent=95
               ):

      dataframe = dataframe.reindex(sorted(dataframe.columns), axis=1)
      dataframe = drop_columns(dataframe,self.variables,self.output_key)

      if include_output == True:
         self.input_array_test = dataframe.drop(columns=[self.output_key])
         self.output_array_test = dataframe[self.output_key]
      else:
         self.input_array_test = dataframe
   
      self.CI_percent = CI_percent
      self.confidence_scalar = st.norm.ppf(1 - ((1 - (CI_percent / 100)) / 2))
      
      self.mean_prediction, self.std_prediction = self.fitted_function.predict(self.input_array_test.to_numpy(), return_std=True)

      self.upper = self.mean_prediction + self.confidence_scalar * self.std_prediction
      self.lower = self.mean_prediction - self.confidence_scalar * self.std_prediction
      self.training_output = self.output_array_train
            
      self.predicted_dataframe = self.input_array_test
      self.predicted_dataframe['predicted_output'] = self.mean_prediction
      if include_output == True:
         self.RMSE = np.sqrt(mean_squared_error(self.output_array_test,self.mean_prediction))
         self.predicted_dataframe['actual_output'] = self.output_array_test
         self.predicted_dataframe['percent_error'] = abs((self.mean_prediction - self.output_array_test)/self.output_array_test)*100
         self.score = self.fitted_function.score(dataframe.drop(columns=[self.output_key]).to_numpy(),dataframe[self.output_key].to_numpy())
      if CI_in_dataframe == True:
         self.predicted_dataframe['upper'] = self.upper
         self.predicted_dataframe['lower'] = self.lower
         
      
      self.min_output = np.amin(self.mean_prediction)
      self.min_output_indices = np.where(self.mean_prediction == self.min_output)
      
      self.max_output = np.amax(self.mean_prediction)
      self.max_output_indices = np.where(self.mean_prediction == self.max_output)

      return self.predicted_dataframe
      
   def find_global_max_min_values(self,
                                  num_points_interpolate=20,
                                  limit_dict=None):
         
      if limit_dict != None:
         self.limit_dict = limit_dict
      
      vars_dict = OrderedDict()
      for key in self.limit_dict:
         vars_dict[key] = np.linspace(start=self.limit_dict[key][0], stop=self.limit_dict[key][1], num=num_points_interpolate)

      vars_grid_array = np.meshgrid(*vars_dict.values())
      min_max_dataframe = pd.DataFrame({})

      for index,key in enumerate(vars_dict.keys()):
         vars_dict[key] = vars_grid_array[index]
         var_vector = vars_dict[key].ravel()
         min_max_dataframe[key] = var_vector

      min_max_dataframe = self.predict(min_max_dataframe)
      
      self.min_output_row = min_max_dataframe.iloc[self.min_output_indices]
      self.max_output_row = min_max_dataframe.iloc[self.max_output_indices]
         
      return self.max_output_row,self.min_output_row
        
   def plot_vars(self,
                 x1=None,
                 x2=None,
                 constants='mean',
                 limit_dict=None,
                 axis=None,
                 num_points=100,
                 contour_step=None,
                 opacity=0.2,
                 title_variable_spacing=3,
                 plotting_grid_value=[0,0],
                 grid_height=1,
                 CI_percent=95,
                 plot_training_points=False,
                 legend_outside=False,
                 contour_type='line',
                 show_max=True,
                 show_min=False,
                 plot_actual_data=False,
                 plot_actual_data_filter_factor=5,
                 show_actual_with_model=True
                 ):
      
      if axis == None:
         fig,axis = plt.subplots(1,1,sharex=True,sharey=True)
         plot_now = True
      else:
         plot_now = False
         
      if contour_step==None:
         contour_step = abs(self.max_train_output - self.min_train_output)/10
      
      color_limits = np.array([self.min_train_output,
                      np.mean([self.min_train_output,self.max_train_output]),
                      self.max_train_output])
      # print(color_limits)
      # color_limits = np.array([88,92,96])
      cmap_colors = ["green","orange","red"]
      
      # color_limits = np.flip(1 - (color_limits/100),0)
      # cmap_colors = np.flip(cmap_colors)
      # show_max=False
      # show_min=True
      # contour_textlabel = '\\eta_{lost}'
      # else:
      contour_textlabel = self.output_key
            
      
      cmap_norm=plt.Normalize(min(color_limits),max(color_limits))
      cmap_tuples = list(zip(map(cmap_norm,color_limits), cmap_colors))
      output_cmap = mcol.LinearSegmentedColormap.from_list("", cmap_tuples)
      
      plot_dataframe = pd.DataFrame({})
      
      if limit_dict == None:
         limit_dict = self.limit_dict
      
      plot_title = ' '

      constants_check=self.variables.copy()
                    
      if (x1 != None) and (x2 == None):
         plot_key1 = x1
         plot_dataframe[plot_key1] = np.linspace(start=limit_dict[plot_key1][0], stop=limit_dict[plot_key1][1], num=num_points)
         constants_check.remove(plot_key1)  
         dimensions=1   
      elif (x1 == None) and (x2 != None):
         plot_key1 = x2
         plot_dataframe[plot_key1] = np.linspace(start=limit_dict[plot_key1][0], stop=limit_dict[plot_key1][1], num=num_points)
         constants_check.remove(plot_key1)
         dimensions=1
      elif (x1 != None) and (x2 != None):
         plot_key1 = x1
         plot_dataframe[plot_key1] = np.linspace(start=limit_dict[plot_key1][0], stop=limit_dict[plot_key1][1], num=num_points)
         constants_check.remove(plot_key1)
         plot_key2 = x2
         plot_dataframe[plot_key2] = np.linspace(start=limit_dict[plot_key2][0], stop=limit_dict[plot_key2][1], num=num_points)
         constants_check.remove(plot_key2)
         dimensions=2
      else:
         sys.exit("Please specify x or y") 
      
      constant_value = {}
      
      if constants == 'mean':
         for constant_key in constants_check:
            constant_value[constant_key] = np.mean(self.input_array_train[constant_key])
         
      elif set(constants_check) != set(constants):
         sys.exit("Constants specified are incorrect")
         
      else:
         # format of constants is {'M2':0.7,'Co':0.6, ...}
         for constant_key in constants:
            if (constants[constant_key] == 'mean'):
               constant_value[constant_key] = np.mean(self.input_array_train[constant_key])
            else:
               constant_value[constant_key] = constants[constant_key]
               
      for constant_key in constants_check:
         if constant_key in ['phi','psi','Lambda']:
            plot_title += '\\' + f'{constant_key} = {constant_value[constant_key]:.3f}'
            plot_title += '\; '*title_variable_spacing
         else:
            plot_title += f'{constant_key} = {constant_value[constant_key]:.3f}'
            plot_title += '\; '*title_variable_spacing
      
      if dimensions == 2:

         X1,X2 = np.meshgrid(plot_dataframe[plot_key1],
                             plot_dataframe[plot_key2]) # creates two matrices which vary across in x and y
         X1_vector = X1.ravel() #vector of "all" x coordinates from meshgrid
         X2_vector = X2.ravel() #vector of "all" y coordinates from meshgrid
         plot_dataframe = pd.DataFrame({})
         plot_dataframe[plot_key1] = X1_vector
         plot_dataframe[plot_key2] = X2_vector
      
      for constant_key in constants_check:
         plot_dataframe[constant_key] = constant_value[constant_key]*np.ones(num_points**dimensions)

      self.predict(plot_dataframe,
                   CI_percent=CI_percent)
            
      if plot_actual_data == True:
         lower_factor = 1 - plot_actual_data_filter_factor/100
         upper_factor = 1 + plot_actual_data_filter_factor/100
         actual_data_df = pd.concat([self.input_array_train.copy(),self.output_array_train.copy()],axis=1)
         
         for constant_key in constants_check:
            val = constant_value[constant_key]
            actual_data_df = actual_data_df[actual_data_df[constant_key] < upper_factor*val]
            actual_data_df = actual_data_df[actual_data_df[constant_key] > lower_factor*val]
            
      if dimensions == 1:
         
         if plot_training_points == True:
            axis.scatter(x=self.input_array_train[plot_key1],
                         y=self.training_output,
                         marker='x',
                         color='red',
                         label='Training data points')

         if show_max == True:
            max_i = np.squeeze(self.max_output_indices)
            axis.text(plot_dataframe[plot_key1][max_i], self.mean_prediction[max_i], f'{self.max_output:.2f}', size=12, color='darkblue')
            axis.scatter(plot_dataframe[plot_key1][max_i], self.mean_prediction[max_i],marker='x',color='darkblue')

         if show_min == True:
            min_i = np.squeeze(self.min_output_indices)
            axis.text(plot_dataframe[plot_key1][min_i], self.mean_prediction[min_i], f'{self.min_output:.2f}', size=12, color='darkblue')
            axis.scatter(plot_dataframe[plot_key1][min_i], self.mean_prediction[min_i],marker='x',color='darkblue')

         if plot_actual_data==True:
               
            poly_degree = int(0.75*actual_data_df.shape[0])
            if poly_degree > 3:
               poly_degree = 3
               
            coefs = np.polynomial.polynomial.polyfit(x=actual_data_df[plot_key1],
                                                     y=actual_data_df[self.output_key],
                                                     deg=poly_degree)

            fit_function = np.polynomial.polynomial.Polynomial(coefs)    # instead of np.poly1d

            x_actual_fit = np.linspace(np.min(actual_data_df[plot_key1]),np.max(actual_data_df[plot_key1]),50)
            y_actual_fit = fit_function(x_actual_fit)
               
            axis.scatter(actual_data_df[plot_key1],
                      actual_data_df[self.output_key],
                      color='darkorange',
                      marker='x')
            axis.plot(x_actual_fit,
                      y_actual_fit,
                      label=r'Polynomial curve from actual data',
                      color='orange',
                      zorder=1e3)
            
         if show_actual_with_model == True:
            
            axis.plot(plot_dataframe[plot_key1], 
                      self.mean_prediction, 
                      label=r'Mean prediction', 
                      color='blue'
                      )
            
            axis.fill_between(x=plot_dataframe[plot_key1],
                              y1=self.upper,
                              y2=self.lower,
                              alpha=opacity,                       
                              label=fr"{self.CI_percent}% confidence interval",
                              color='blue'
                              )
            
            y_range = np.amax(self.upper) - np.amin(self.lower)
            axis.set_xlim(limit_dict[plot_key1][0],
                        limit_dict[plot_key1][1],
                        auto=True)
            axis.set_ylim(bottom=np.amin(self.lower)-0.1*y_range,
                           top=np.amax(self.upper)+0.1*y_range,
                           auto=True)
            
         if plotting_grid_value==[0,0]:
            if legend_outside == True:
               leg = axis.legend(loc='upper left',
                                 bbox_to_anchor=(1.02,1.0),
                                 borderaxespad=0,
                                 frameon=True,
                                 ncol=1,
                                 prop={'size': 10})
            else:
               leg = axis.legend()
            leg.set_draggable(state=True)
         
         if plotting_grid_value[0] == (grid_height-1):
            if plot_key1 in ['phi','psi','Lambda']:
               xlabel_string = '\\'+plot_key1
               axis.set_xlabel(fr"$ {xlabel_string} $")
            else:
               axis.set_xlabel(fr"${plot_key1}$")
               
         if plotting_grid_value[1] == 0:
            axis.set_ylabel(self.output_key)

         axis.grid(linestyle = '--', linewidth = 0.5)
         
      elif dimensions == 2:
         
         min_level = np.floor(self.min_output/contour_step)*contour_step
         max_level = np.ceil(self.max_output/contour_step)*contour_step
         contour_levels = np.arange(min_level,max_level,contour_step)
         
         mean_prediction_grid = self.mean_prediction.reshape(num_points,num_points)
         upper_grid = self.upper.reshape(num_points,num_points)
         lower_grid = self.lower.reshape(num_points,num_points)
         
         if show_max == True:
            max_i = np.squeeze(self.max_output_indices)
            axis.text(X1.ravel()[max_i], X2.ravel()[max_i], f'{self.max_output:.2f}', size=12, color='dark'+cmap_colors[2])
            axis.scatter(X1.ravel()[max_i], X2.ravel()[max_i],color=cmap_colors[2],marker='x')

         if show_min == True:
            min_i = np.squeeze(self.min_output_indices)
            axis.text(X1.ravel()[min_i], X2.ravel()[min_i], f'{self.min_output:.2f}', size=12, color='dark'+cmap_colors[0])
            axis.scatter(X1.ravel()[min_i], X2.ravel()[min_i],color=cmap_colors[0],marker='x')
         
         if plot_training_points == True:
            training_points_plot = axis.scatter(x=self.input_array_train[plot_key1],
                                                y=self.input_array_train[plot_key2],
                                                marker='x',
                                                color='blue'
                                                )
         
         if contour_type=='line':
            predicted_plot = axis.contour(X1, X2, mean_prediction_grid,levels=contour_levels,cmap=output_cmap,norm=cmap_norm)
            axis.clabel(predicted_plot, inline=1, fontsize=14)
            for contour_level_index,contour_level in enumerate(contour_levels):  #clear this up
               confidence_array = (upper_grid>=contour_level) & (lower_grid<=contour_level)

               contour_color = output_cmap(cmap_norm(contour_level))

               confidence_plot = axis.contourf(X1,X2,confidence_array, levels=[0.5, 2], alpha=opacity,cmap = mcol.ListedColormap([contour_color])) 
               h2,_ = confidence_plot.legend_elements()
               
         elif contour_type=='continuous':
            predicted_plot = axis.contourf(X1, X2, mean_prediction_grid,cmap=output_cmap,norm=cmap_norm,levels=contour_levels,extend='both')
         
         else:
            sys.exit('Please specify "continuous" or "line" for contour_type')
            
         h1,_ = predicted_plot.legend_elements()
         
         if plotting_grid_value==[0,0]:
            
            if plot_training_points == True:
               if contour_type == 'line':
                  handles = [h1[0], h2[0], training_points_plot]
                  labels = [fr'$ {contour_textlabel} $, Mean prediction',
                           fr"{self.CI_percent}% confidence interval",
                           'Training data points']
               else:
                  handles = [h1[0], training_points_plot]
                  labels = [fr'$ {contour_textlabel} $, Mean prediction',
                            'Training data points']
            else:
               if contour_type == 'line':
                  handles = [h1[0], h2[0]]
                  labels = [fr'$ {contour_textlabel} $, Mean prediction',
                           fr"{self.CI_percent}% confidence interval", 
                           'Training data points']
               else:
                  handles = [h1[0]]
                  labels = [fr'$ {contour_textlabel} $, Mean prediction']
                  
            if legend_outside == True:
               leg = axis.legend(handles=handles,
                                 labels=labels,
                                 loc='upper left',
                                 bbox_to_anchor=(1.02,1.0),
                                 borderaxespad=0,
                                 frameon=True,
                                 ncol=1,
                                 prop={'size': 10})
            else:
               leg = axis.legend(handles=handles,
                                 labels=labels)

            leg.set_draggable(state=True)
         
         if plotting_grid_value[0] == (grid_height-1):
            if plot_key1 in ['phi','psi','Lambda']:
               xlabel_string1 = '\\'+plot_key1
               axis.set_xlabel(fr"$ {xlabel_string1} $")
            else:
               axis.set_xlabel(f"${plot_key1}$")
         
         if plotting_grid_value[1] == 0:
            if plot_key2 in ['phi','psi','Lambda']:
               xlabel_string2 = '\\'+plot_key2
               axis.set_ylabel(fr"$ {xlabel_string2} $")
            else:
               axis.set_ylabel(f"${plot_key2}$")
         
         axis.set_xlim(limit_dict[plot_key1][0],
                       limit_dict[plot_key1][1],
                       auto=True)
         axis.set_ylim(limit_dict[plot_key2][0],
                       limit_dict[plot_key2][1],
                       auto=True)
         
         axis.grid(linestyle = '--', linewidth = 0.5)
          
      else:
         sys.exit('Somehow wrong number of dimensions')
      
      if self.fit_dimensions>2:
         axis.set_title(fr'$ {plot_title} $',size=10)
      
      if plot_now == True:
         fig.tight_layout()
         plt.show()
         
      return plot_dataframe
      
   def plot_accuracy(self,
                     testing_dataframe,
                     axis=None,
                     line_error_percent=5,
                     CI_percent=95,
                     identify_outliers=True,
                     title_variable_spacing=3,
                     plot_errorbars=True,
                     score_variable='R2'
                     ):
      
      runid_dataframe = testing_dataframe['runid']   
      testing_dataframe = drop_columns(testing_dataframe,self.variables,self.output_key)
      
      self.predict(testing_dataframe,
                   include_output=True,
                   CI_in_dataframe=True,
                   CI_percent=CI_percent,
                   )
      
      if axis == None:
         fig,ax = plt.subplots(1,1,sharex=True,sharey=True)
         
      self.predicted_dataframe['runid'] = runid_dataframe
         
      predicted_values = self.predicted_dataframe['predicted_output']
      actual_values = self.predicted_dataframe['actual_output']
      upper_errorbar = (self.predicted_dataframe['upper']-predicted_values)
      lower_errorbar = (predicted_values-self.predicted_dataframe['lower'])
      
      if identify_outliers == True:
         outliers = self.predicted_dataframe[self.predicted_dataframe['percent_error'] > line_error_percent]
               
         for row_index,row in outliers.iterrows():
            value_string = f''
            newline=' $\n$ '
            for col_index,col in enumerate(outliers):
               
               if col in ['phi','psi','Lambda']:
                  if (col_index%2==0) and (col_index!=0):
                     value_string += newline
                  value_string += '\\' + f'{col}={row[col]:.3f}'
                  value_string += '\; '*title_variable_spacing
               else:
                  if (col_index%2==0) and (col_index!=0):
                     value_string += newline
                  value_string += f'{col}={row[col]:.3f}'
                  value_string += '\; '*title_variable_spacing
                  
               
            ax.scatter(row['actual_output'], row['predicted_output'],color='blue',marker=f'${row_index}$',s=160,label=fr'$ runID={row["runid"]:.0f} $',linewidths=0.1)
      
      limits_array = np.linspace(actual_values.min(),actual_values.max(),1000)
      upper_limits_array = (1+line_error_percent/100)*limits_array
      lower_limits_array = (1-line_error_percent/100)*limits_array
      
      if identify_outliers == True:
         non_outliers = self.predicted_dataframe[self.predicted_dataframe['percent_error'] < line_error_percent]
         ax.scatter(non_outliers['actual_output'],non_outliers['predicted_output'],marker='x',label='Testing data points',color='blue')
      else:
         ax.scatter(actual_values,predicted_values,marker='x',label='Test data points',color='blue')
      ax.plot(limits_array,limits_array,linestyle='solid',color='red',label = r'$f(x)=x$')
      ax.plot(limits_array,upper_limits_array,linestyle='dotted',color='red',label = f'{line_error_percent}% error interval')
      ax.plot(limits_array,lower_limits_array,linestyle='dotted',color='red')
      if plot_errorbars==True:
         ax.errorbar(actual_values,
                     predicted_values,
                     (upper_errorbar,lower_errorbar),
                     fmt='none',
                     capsize=2.0,
                     ecolor='darkblue',
                     label = fr"{self.CI_percent}% confidence interval"
                     )
      if score_variable=='both':
         ax.set_title(fr'RMSE = {self.RMSE:.2e}    $R^2$ = {self.score:.3f}')
      elif score_variable=='R2':
         ax.set_title(fr'$R^2$ = {self.score:.3f}')
      elif score_variable=='RMSE':
         ax.set_title(fr'RMSE = {self.RMSE:.2e}')
      else:
         sys.exit("Enter suitable score variable from ['both','R2','RMSE']")
      
      ax.set_xlabel(f'{self.output_key} (actual)')
      ax.set_ylabel(f'{self.output_key} (prediction)')
         
      leg = ax.legend(loc='upper left',
                      bbox_to_anchor=(1.02,1.0),
                      borderaxespad=0,
                      frameon=True,
                      ncol=1,
                      prop={'size': 10})
      leg.set_draggable(state=True)
      
      ax.grid(linestyle = '--', linewidth = 0.5)
      
      if axis == None:
         fig.tight_layout()
         plt.show()
      
   def plot(self,
            x1=None,
            x2=None,
            constants='mean',          # form: {'M':0.5,'Co':0.5}
            gridvars={},               # form: {'M':[0.5,0.6,0.7],'Co:[0.6,0.7]}
            rotate_grid=False,
            limit_dict=None,
            num_points=100,
            contour_step=None,
            opacity=0.3,
            title_variable_spacing=3,
            with_arrows=True,
            CI_percent=95,
            plot_training_points=False,
            legend_outside=False,
            contour_type='line',
            show_max=True,
            show_min=False,
            plot_actual_data=False,
            plot_actual_data_filter_factor=5,
            show_actual_with_model=True,
            optimum_plot=False
            ):

      grid_constants=self.variables.copy()
      
      if x1 != None:
         grid_constants.remove(x1)  
      if x2 != None:
         grid_constants.remove(x2)  
      if (x1==None) and (x2==None):
         sys.exit('Must state wither correct x1 or correct x2')
      
      grid_shape, grid_keys=[1,1], {0:' ',1:' '}
      
      if rotate_grid==True:
         grid_index=1
      else:
         grid_index=0
         
      if gridvars != {}:
         for var in grid_constants:
            if var in [x1,x2]:
               sys.exit('Already plotting grid variable')
            elif var in gridvars:
               grid_shape[grid_index] = len(gridvars[var])
               grid_keys[grid_index] = var
               grid_index = not grid_index
      else:
         grid_index=0
               
      num_rows=grid_shape[0]
      num_columns=grid_shape[1]
      
      fig, axes = plt.subplots(nrows=num_rows,
                               ncols=num_columns,
                               sharex=True,
                               sharey=True
                               )
      
      for indices, axis in np.ndenumerate(axes):
         
         print('plot',indices)
         
         if (num_columns == 1) and (num_rows > 1):
            i = np.squeeze(indices)
            j = 0
         elif (num_columns > 1) and (num_rows == 1):
            j = np.squeeze(indices)
            i = 0
         elif (num_columns > 1) and (num_rows > 1):
            (i,j) = indices
         else:
            i,j=0,0
            
         constant_dict = {}
         
         for var in grid_constants:
            if (var in gridvars) and (grid_keys[0]==var):
               constant_dict[var] = gridvars[var][i]

            elif (var in gridvars) and (grid_keys[1]==var):
               constant_dict[var] = gridvars[var][j]
            else:
               if constants=='mean':
                  constant_dict[var] = 'mean'
               else:
                  constant_dict[var] = constants[var]
         if optimum_plot == True:
            self.plot_optimum(opt_var=x1,
                              vary_var=x2,
                              constants=constant_dict,
                              limit_dict=limit_dict,
                              plot_actual_data_filter_factor=plot_actual_data_filter_factor,
                              title_variable_spacing=title_variable_spacing,
                              num_points=num_points,
                              axis=axis,
                              plotting_grid_value=[i,j],
                              grid_height=num_rows,
                              plot_actual_data=plot_actual_data,
                              legend_outside=legend_outside)
         else:
            self.plot_vars(x1=x1,
                           x2=x2,
                           constants=constant_dict,
                           limit_dict=limit_dict,
                           axis=axis,
                           num_points=num_points,
                           contour_step=contour_step,
                           opacity=opacity,
                           title_variable_spacing=title_variable_spacing,
                           plotting_grid_value=[i,j],
                           grid_height=num_rows,
                           CI_percent=CI_percent,
                           plot_training_points=plot_training_points,
                           legend_outside=legend_outside,
                           contour_type=contour_type,
                           show_max=show_max,
                           show_min=show_min,
                           plot_actual_data=plot_actual_data,
                           plot_actual_data_filter_factor=plot_actual_data_filter_factor,
                           show_actual_with_model=show_actual_with_model
                           )

      if (num_columns>1) or (num_rows>1):
         if with_arrows==True:
            if num_columns >1:
               if grid_keys[1] in ['phi','psi','Lambda']:
                  xlabel_string1 = '\\'+grid_keys[1]+' \\rightarrow'
                  fig.supxlabel(fr"$ {xlabel_string1} $")
               else:
                  fig.supxlabel(f"$ {grid_keys[1]} \\rightarrow $")
            if num_rows >1:
               if grid_keys[0] in ['phi','psi','Lambda']:
                  xlabel_string2 = '\\leftarrow \\'+grid_keys[0]
                  fig.supylabel(fr"$ {xlabel_string2} $")
               else:
                  fig.supylabel(f"$\\leftarrow {grid_keys[0]} $")
         else:
            if num_columns >1:
               if grid_keys[1] in ['phi','psi','Lambda']:
                  xlabel_string1 = '\\'+grid_keys[1]
                  fig.supxlabel(fr"$ {xlabel_string1} $")
               else:
                  fig.supxlabel(f"${grid_keys[1]} $")
            if num_rows >1:   
               if grid_keys[0] in ['phi','psi','Lambda']:
                  xlabel_string2 = '\\'+grid_keys[0]
                  fig.supylabel(fr"$ {xlabel_string2} $")
               else:
                  fig.supylabel(f"${grid_keys[0]} $")
                  
      plt.show()
      
   def matern_kernel(self,
                     N,
                     bounds = (1e-2,1e3)):
      L = np.ones(N)
      L_bounds = []
      for i in range(N):
         L_bounds.append(bounds)
      
      return kernels.Matern(length_scale = L,
                            length_scale_bounds=L_bounds,
                            nu=2.5
                            )

   def plot_optimum(self,
                    opt_var,
                    vary_var,
                    constants,
                    limit_dict=None,
                    plot_actual_data_filter_factor=15,
                    title_variable_spacing=3,
                    num_points=50,
                    axis=None,
                    plotting_grid_value=[0,0],
                    grid_height=1,
                    plot_actual_data=False,
                    legend_outside = False):
      
      
      if axis == None:
         fig,axis = plt.subplots(1,1,sharex=True,sharey=True)
         plot_now = True
      else:
         plot_now = False
         
      if limit_dict == None:
         limit_dict = self.limit_dict

      constants_check=self.variables.copy()
      constants_check.remove(vary_var) 
      constants_check.remove(opt_var) 
      plot_title = ''
      # filter by factor% error
      lower_factor = 1 - plot_actual_data_filter_factor/100
      upper_factor = 1 + plot_actual_data_filter_factor/100
      actual_data_df_datum = pd.concat([self.input_array_train.copy(),self.output_array_train.copy()],axis=1)
      
      vary_var_values = np.linspace(np.min(actual_data_df_datum[vary_var]),np.max(actual_data_df_datum[vary_var]),num_points)
      opt_values = np.zeros(num_points)
      opt_values_GPR = np.zeros(num_points)
      plot_dataframe = pd.DataFrame({})
      plot_dataframe[opt_var] = np.linspace(np.min(actual_data_df_datum[opt_var]),np.max(actual_data_df_datum[opt_var]),num_points)
      
      constant_value = {}
      
      if constants == 'mean':
         for constant_key in constants_check:
            constant_value[constant_key] = np.mean(self.input_array_train[constant_key])
         
      elif set(constants_check) != set(constants):
         sys.exit("Constants specified are incorrect")
         
      else:
         # format of constants is {'M2':0.7,'Co':0.6, ...}
         for constant_key in constants:
            if (constants[constant_key] == 'mean'):
               constant_value[constant_key] = np.mean(self.input_array_train[constant_key])
            else:
               constant_value[constant_key] = constants[constant_key]
               
      for constant_key in constants_check:
         plot_dataframe[constant_key] = constant_value[constant_key]*np.ones(num_points)
         val = constant_value[constant_key]

         actual_data_df_datum = actual_data_df_datum[actual_data_df_datum[constant_key] < upper_factor*val]
         actual_data_df_datum = actual_data_df_datum[actual_data_df_datum[constant_key] > lower_factor*val]
         if constant_key in ['phi','psi','Lambda']:
            plot_title += '\\' + f'{constant_key} = {constant_value[constant_key]:.3f}'
            plot_title += '\; '*title_variable_spacing
         else:
            plot_title += f'{constant_key} = {constant_value[constant_key]:.3f}'
            plot_title += '\; '*title_variable_spacing
            
      for i,vary_var_val in enumerate(vary_var_values):
         
         actual_data_df = actual_data_df_datum.copy()

         # vary var
         plot_dataframe[vary_var] = vary_var_val*np.ones(num_points)

         actual_data_df = actual_data_df[actual_data_df[vary_var] < upper_factor*vary_var_val]
         actual_data_df = actual_data_df[actual_data_df[vary_var] > lower_factor*vary_var_val]
         
         if actual_data_df.shape[0] >= 5:

            poly_degree = 3
               
            coefs = np.polynomial.polynomial.polyfit(x=actual_data_df[opt_var],
                                                      y=actual_data_df[self.output_key],
                                                      deg=poly_degree)

            fit_function = np.polynomial.polynomial.Polynomial(coefs)    # instead of np.poly1d

            x_actual_fit = np.linspace(np.min(actual_data_df[opt_var]),np.max(actual_data_df[opt_var]),num_points)
            y_actual_fit = fit_function(x_actual_fit)
            
            
            y_min = np.amin(y_actual_fit)
            opt_val = x_actual_fit[np.where(y_actual_fit == y_min)][0]
            opt_values[i] = opt_val
            
         self.predict(plot_dataframe)
         min_i = np.squeeze(self.min_output_indices)
         opt_val_GPR = plot_dataframe[opt_var][min_i]
         opt_values_GPR[i] = opt_val_GPR
         
      axis.scatter(vary_var_values[opt_values !=0],
                   opt_values[opt_values !=0],
                   marker='x',
                   color='red',
                   label=f'CFD datapoints (margin={plot_actual_data_filter_factor}%)')

      axis.plot(vary_var_values,
                opt_values_GPR,
                color='darkblue',
                label='GPR model')
      axis.set_xlabel(vary_var)
      axis.set_ylabel('$'+opt_var+r'_{\mathrm{optimum}}$')
      axis.set_title(fr'$ {plot_title} $',size=10)
      if plotting_grid_value==[0,0]:
         if legend_outside == True:
            leg = axis.legend(loc='upper left',
                              bbox_to_anchor=(1.02,1.0),
                              borderaxespad=0,
                              frameon=True,
                              ncol=1,
                              prop={'size': 10})
         else:
            leg = axis.legend()
         leg.set_draggable(state=True)
      
      # axis.scatter(actual_data_df[opt_var],
      #             actual_data_df[self.output_key],
      #             color='darkorange',
      #             marker='x')
      # axis.plot(x_actual_fit,
      #             y_actual_fit,
      #             label=r'Polynomial curve from actual data',
      #             color='orange',
      #             zorder=1e3)
      
      if plot_now == True:
         fig.tight_layout()
         plt.show()

class turbine:
    def __init__(self,phi,psi,M2,Co):
        
        if np.isscalar(phi) and np.isscalar(psi) and np.isscalar(M2) and np.isscalar(Co):
            self.no_points = 1
            self.phi = np.array([phi])
            self.psi = np.array([psi])
            self.M2 = np.array([M2])
            self.Co = np.array([Co])
        elif not np.isscalar(phi) and not np.isscalar(psi) and not np.isscalar(M2) and not np.isscalar(Co):
            self.phi = np.array(phi)
            self.psi = np.array(psi)
            self.M2 = np.array(M2)
            self.Co = np.array(Co)
            self.no_points = len(self.phi)
        else:
            sys.exit('Incorrect input types')
            
        self.htr = 0.9
        self.AR = [1.6,1.6]
        
        self.spf_stator,self.spf_rotor = 0.5,0.5
        self.spf = [self.spf_stator,self.spf_rotor]
        
        self.recamber_le_stator,self.recamber_le_rotor = 0.0,0.0
        self.recamber_le = [self.recamber_le_stator,self.recamber_le_rotor]
        
        self.ga = 1.33
        self.Rgas = 272.9
        self.cp = self.Rgas * self.ga / (self.ga - 1.0)
        self.tte = 0.015
        self.delta = 0.1
        
        self.Lambda=0.5
        
        #geom
        self.Rle_stator,self.Rle_rotor = [0.04,0.04]
        
        #datum dimensional
        self.To1 = 1600.0
        self.Po1 = 1600000.0
        self.Omega = 314.159
        self.Re = 2e6

    def get_Al(self):
    
        Al2_model = turbine_GPR('Al2a')
        Al3_model = turbine_GPR('Al3')
        
        Al1 = np.zeros(self.no_points)
        Al2 = np.array(Al2_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'M2':self.M2,
                                                    'Co':self.Co}))['predicted_output'])
        Al3 = np.array(Al3_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'M2':self.M2,
                                                    'Co':self.Co}))['predicted_output'])
        self.Al1 = Al1
        self.Al2 = Al2
        self.Al3 = Al3
        self.Al = np.array([Al1,Al2,Al3])
        
        return self.Al

    def get_stagger(self):
        
        stagger_stator_model = turbine_GPR('stagger_stator')
        stagger_rotor_model = turbine_GPR('stagger_rotor')
        
        stagger_stator = np.array(stagger_stator_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                                        'psi':self.psi,
                                                                        'M2':self.M2,
                                                                        'Co':self.Co}))['predicted_output'])
        stagger_rotor = np.array(stagger_rotor_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                                        'psi':self.psi,
                                                                        'M2':self.M2,
                                                                        'Co':self.Co}))['predicted_output'])
        self.stagger_stator = stagger_stator
        self.stagger_rotor = stagger_rotor
        self.stagger = np.array([stagger_stator,stagger_rotor])
        return self.stagger

    def get_zeta(self):
        zeta_stator_model = turbine_GPR('zeta_stator') #maybe improve this model
        
        zeta_stator = np.array(zeta_stator_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'M2':self.M2,
                                                    'Co':self.Co}))['predicted_output'])
        zeta_rotor = np.ones(self.no_points)
        
        self.zeta_stator = zeta_stator
        self.zeta_rotor = zeta_rotor
        self.zeta = np.array([zeta_stator,zeta_rotor])
        
        return self.zeta

    def get_s_cx(self):
        s_cx_stator_model = turbine_GPR('s_cx_stator')
        s_cx_rotor_model = turbine_GPR('s_cx_rotor')
        
        s_cx_stator = np.array(s_cx_stator_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'M2':self.M2,
                                                    'Co':self.Co}))['predicted_output'])
        s_cx_rotor = np.array(s_cx_rotor_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'M2':self.M2,
                                                    'Co':self.Co}))['predicted_output'])
        
        self.s_cx_stator = s_cx_stator
        self.s_cx_rotor = s_cx_rotor
        self.s_cx = np.array([s_cx_stator,s_cx_rotor])
        
        return self.s_cx
    
    def get_loss_rat(self):
        loss_rat_model = turbine_GPR('loss_rat')
        
        self.get_Yp()
        
        self.loss_rat = np.array(loss_rat_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'Yp_stator':self.Yp_stator,
                                                    'Yp_rotor':self.Yp_rotor,
                                                    'Co':self.Co}))['predicted_output'])
        
        return self.loss_rat

    def get_eta_lost(self):
        eta_lost_model = turbine_GPR('eta_lost')
        
        self.get_Yp()
        
        self.eta_lost = np.array(eta_lost_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                    'psi':self.psi,
                                                    'M2':self.M2,
                                                    'Co':self.Co,
                                                    'Yp_stator':self.Yp_stator,
                                                    'Yp_rotor':self.Yp_rotor}))['predicted_output'])
        
        return self.eta_lost
    
    def get_t_ps(self):
        self.t_ps_stator = 0.205*np.ones(self.no_points)
        self.t_ps_rotor = 0.250*np.ones(self.no_points)
        self.t_ps = np.array([self.t_ps_stator,self.t_ps_rotor])
        return self.t_ps
    
    def get_t_ss(self):
        self.t_ss_stator = 0.29*np.ones(self.no_points)
        self.t_ss_rotor = 0.30*np.ones(self.no_points)
        self.t_ss = np.array([self.t_ss_stator,self.t_ps_rotor])
        return self.t_ss

    def get_Yp(self):
        Yp_stator_model = turbine_GPR('Yp_stator')
        Yp_rotor_model = turbine_GPR('Yp_rotor')
        
        self.get_stagger()
        self.get_s_cx()
        self.get_Al()
        
        Yp_stator = np.array(Yp_stator_model.predict(pd.DataFrame(data={'s_cx_stator':self.s_cx_stator,
                                                                        'stagger_stator':self.stagger_stator,
                                                                        'M2':self.M2,
                                                                        'Al2a':self.Al2}))['predicted_output'])
        Yp_rotor = np.array(Yp_rotor_model.predict(pd.DataFrame(data={'s_cx_rotor':self.s_cx_rotor,
                                                                        'psi':self.psi,
                                                                        'M2':self.M2,
                                                                        'stagger_rotor':self.stagger_rotor}))['predicted_output'])
        self.Yp_stator = Yp_stator
        self.Yp_rotor = Yp_rotor
        self.Yp = np.array([Yp_stator,Yp_rotor])
        return self.Yp
    
    def get_beta(self):
        beta_rotor_model = turbine_GPR('beta_rotor')
        self.beta_rotor = np.array(beta_rotor_model.predict(pd.DataFrame(data={'phi':self.phi,
                                                                              'psi':self.psi,
                                                                              'M2':self.M2,
                                                                              'Co':self.Co}))['predicted_output'])
        
        self.beta_stator = 10.5*np.ones(self.no_points)
        self.beta = [self.beta_stator,self.beta_rotor]
        return self.beta
    
    def get_lean(self):
        self.lean_stator = 0.03*np.ones(self.no_points)  #ballpark
        self.lean_rotor = np.zeros(self.no_points)
        self.lean = np.array([self.lean_stator,self.lean_rotor])
        return self.lean

    def get_recamber_te(self):
        self.recamber_te_stator = np.zeros(self.no_points) #ballpark
        self.recamber_te_rotor = np.zeros(self.no_points)  #ballpark
        self.recamber_te = np.array([self.recamber_te_stator,self.recamber_te_rotor])
        return self.recamber_te
    
    def get_max_t_loc_ps(self):
        self.max_t_loc_ps_stator = 0.35*np.ones(self.no_points)   #ballpark
        self.max_t_loc_ps_rotor = 0.37*np.ones(self.no_points)    #ballpark
        self.max_t_loc_ps = np.array([self.max_t_loc_ps_stator,self.max_t_loc_ps_rotor])
        return self.max_t_loc_ps
    
    def get_max_t_loc_ss(self):
        self.max_t_loc_ss_stator = 0.40*np.ones(self.no_points)   #ballpark
        self.max_t_loc_ss_rotor = 0.32*np.ones(self.no_points)    #ballpark
        self.max_t_loc_ss = np.array([self.max_t_loc_ss_stator,self.max_t_loc_ps_rotor])
        return self.max_t_loc_ss
    
    def get_nondim(self):

        Al = self.get_Al()
        loss_ratio = self.get_loss_rat()
        eta_lost = self.get_eta_lost()
        self.get_Yp()
        self.eta = 100-100*eta_lost
        
        zeta = self.get_zeta() #zeta rotor assumed=1.0
        cosAl = np.cos(np.radians(Al))
            
        # Get non-dimensional velocities from definition of flow coefficient
        Vx_U1,Vx_U2,Vx_U3 = self.phi*zeta[0], self.phi, self.phi*zeta[1]
        Vx_U = np.array([Vx_U1,Vx_U2,Vx_U3])
        Vt_U = Vx_U * np.tan(np.radians(Al))
        V_U = np.sqrt(Vx_U ** 2.0 + Vt_U ** 2.0)

        # Change reference frame for rotor-relative velocities and angles
        Vtrel_U = Vt_U - 1.0
        Vrel_U = np.sqrt(Vx_U ** 2.0 + Vtrel_U ** 2.0)
        Alrel = np.degrees(np.arctan2(Vtrel_U, Vx_U))

        # Use Mach number to get U/cpTo1
        V_sqrtcpTo2 = compflow.V_cpTo_from_Ma(self.M2, self.ga)
        U_sqrtcpTo1 = V_sqrtcpTo2 / V_U[1]
        
        Usq_cpTo1 = U_sqrtcpTo1 ** 2.0

        # Non-dimensional temperatures from U/cpTo Ma and stage loading definition
        cpTo1_Usq = 1.0 / Usq_cpTo1
        cpTo2_Usq = cpTo1_Usq
        cpTo3_Usq = (cpTo2_Usq - self.psi)

        # Turbine
        cpTo_Usq = np.array([cpTo1_Usq, cpTo2_Usq, cpTo3_Usq])
        
        # Mach numbers and capacity from compressible flow relations
        Ma = compflow.Ma_from_V_cpTo(V_U / np.sqrt(cpTo_Usq), self.ga)
        Marel = Ma * Vrel_U / V_U
        Q = compflow.mcpTo_APo_from_Ma(Ma, self.ga)
        Q_Q1 = Q / Q[0]

        # Use polytropic effy to get entropy change
        To_To1 = cpTo_Usq / cpTo_Usq[0]
        Ds_cp = -(1.0 - 1.0 / (1.0 - eta_lost)) * np.log(To_To1[-1])

        # Somewhat arbitrarily, split loss using loss ratio (default 0.5)
        s_cp = np.vstack((np.zeros(self.no_points), loss_ratio, np.ones(self.no_points))) * Ds_cp

        # Convert to stagnation pressures
        Po_Po1 = np.exp((self.ga / (self.ga - 1.0)) * (np.log(To_To1) + s_cp))

        # Account for cooling or bleed flows
        mdot_mdot1 = 1.0

        # Use definition of capacity to get flow area ratios
        # Area ratios = span ratios because rm = const
        Dr_Drin = mdot_mdot1 * np.sqrt(To_To1) / Po_Po1 / Q_Q1 * cosAl[0] / cosAl

        # Evaluate some other useful secondary aerodynamic parameters
        T_To1 = To_To1 / compflow.To_T_from_Ma(Ma, self.ga)
        P_Po1 = Po_Po1 / compflow.Po_P_from_Ma(Ma, self.ga)
        Porel_Po1 = P_Po1 * compflow.Po_P_from_Ma(Marel, self.ga)
        
        # Turbine
        Lam = (T_To1[2] - T_To1[1]) / (T_To1[2] - T_To1[0])
        
        self.Al = Al
        self.Alrel = Alrel
        self.Ma = Ma
        self.Marel =Marel
        self.Ax_Ax1 = Dr_Drin
        self.U_sqrtcpTo1 = U_sqrtcpTo1
        self.Po_Po1 = Po_Po1
        self.To_To1 = To_To1
        self.Vt_U = Vt_U
        self.Vtrel_U = Vtrel_U
        self.V_U = V_U
        self.Vrel_U = Vrel_U
        self.P_Po1 = P_Po1
        self.Porel_Po1 = Porel_Po1
        self.T_To1 = T_To1
        self.mdot_mdot1 = mdot_mdot1
        self.Lam = Lam

    def free_vortex_vane(self,rh,rc,rm):
        """Evaluate vane flow angles assuming a free vortex."""
        
        Al = np.array(self.get_Al())
        
        rh_vane = rh[:2].reshape(-1, 1)
        rc_vane = rc[:2].reshape(-1, 1)
        Al_vane = Al[:2].reshape(-1, 1)

        r_rm = (np.reshape(self.spf_stator, (1, -1)) * (rh_vane - rc_vane) + rh_vane) / rm

        return np.degrees(np.arctan(np.tan(np.radians(Al_vane)) / r_rm))

    def free_vortex_blade(self,rh,rc,rm):
        """Evaluate blade flow angles assuming a free vortex."""
        
        Al = np.array(self.get_Al())
        
        rh_blade = rh[1:].reshape(-1, 1)
        rc_blade = rc[1:].reshape(-1, 1)
        Al_blade = Al[1:].reshape(-1, 1)

        r_rm = (np.reshape(self.spf_rotor, (1, -1)) * (rc_blade - rh_blade) + rh_blade) / rm

        return np.degrees(np.arctan(np.tan(np.radians(Al_blade)) / r_rm - r_rm / self.phi))

    def dim_from_omega(self, Omega, To1, Po1):
        """Scale a mean-line design and evaluate geometry from omega."""
   
        
        self.get_nondim()
        
        self.P = self.P_Po1 * Po1
        self.Po = self.Po_Po1 * Po1
        self.Porel = self.Porel_Po1 * Po1
        self.T = self.T_To1 * To1
        self.To = self.To_To1 * To1

        cpTo1 = self.cp * To1
        U = self.U_sqrtcpTo1 * np.sqrt(cpTo1)
        rm = U / Omega
        
        self.V = self.V_U*U
        self.Vt = self.Vt_U*U
        self.Vtrel = self.Vtrel_U*U
        self.Vrel = self.Vrel_U*U

        # Use hub-to-tip ratio to set span (mdot will therefore float)
        Dr_rm = 2.0 * (1.0 - self.htr) / (1.0 + self.htr)

        Dr = rm * Dr_rm * np.array(self.Ax_Ax1) / self.Ax_Ax1[1]

        Q1 = compflow.mcpTo_APo_from_Ma(self.Ma[0], self.ga)

        Ax1 = 2.0 * np.pi * rm * Dr[0]
        mdot1 = Q1 * Po1 * Ax1 * np.cos(np.radians(self.Al[0])) / np.sqrt(cpTo1)

        # Chord from aspect ratio
        span = np.array([np.mean(Dr[i : (i + 2)]) for i in range(2)])
        cx = span / self.AR
        
        s_cx = self.get_s_cx()
        
        self.rm = rm
        self.U = U
        self.Dr = Dr
        self.rh = rm - Dr / 2.0
        self.rc = rm + Dr / 2.0
        self.Ax1 = Ax1
        self.mdot1 = mdot1
        
        self.span = span
        self.chord_x = cx
        self.pitch_stator = s_cx[0]*cx[0]
        self.pitch_rotor = s_cx[1]*cx[1]
        
        self.num_blades_stator = 2*np.pi*rm/self.pitch_stator
        self.num_blades_rotor = 2*np.pi*rm/self.pitch_rotor
        
        self.Omega = Omega
        self.Po1 = Po1
        self.To1 = To1
        
        self.chi = np.stack((self.free_vortex_vane(self.rh,self.rc,self.rm),
                             self.free_vortex_blade(self.rh,self.rc,self.rm)
                             ))
 
    def dim_from_mdot(self, mdot1, To1, Po1):
        """Scale a mean-line design and evaluate geometry from mdot."""
        
        self.get_nondim()
        
        self.P = self.P_Po1 * Po1
        self.Po = self.Po_Po1 * Po1
        self.Porel = self.Porel_Po1 * Po1
        self.T = self.T_To1 * To1
        self.To = self.To_To1 * To1

        cpTo1 = self.cp * To1
        Q1 = compflow.mcpTo_APo_from_Ma(self.Ma[0], self.ga)
        
        Ax1 = np.sqrt(cpTo1) * mdot1 / (Q1 * Po1 * np.cos(np.radians(self.Al[0])))
        Dr_rm = 2.0 * (1.0 - self.htr) / (1.0 + self.htr)
        
        rm = np.sqrt(Ax1 * self.Ax_Ax1[1] / (2.0 * np.pi * Dr_rm * self.Ax_Ax1[0])) 
        
        U = self.U_sqrtcpTo1 * np.sqrt(cpTo1)
        Omega = U / rm
        
        self.V = self.V_U*U
        self.Vt = self.Vt_U*U
        self.Vtrel = self.Vtrel_U*U
        self.Vrel = self.Vrel_U*U

        Dr = rm * Dr_rm * np.array(self.Ax_Ax1) / self.Ax_Ax1[1]

        # Chord from aspect ratio
        span = np.array([np.mean(Dr[i : (i + 2)]) for i in range(2)])
        cx = span / self.AR
        
        s_cx = self.get_s_cx()
        
        self.rm = rm
        self.U = U
        self.Dr = Dr
        self.rh = rm - Dr / 2.0
        self.rc = rm + Dr / 2.0
        self.Ax1 = Ax1
        self.mdot1 = mdot1
        
        self.span = span
        self.chord_x = cx
        self.pitch_stator = s_cx[0]*cx
        self.pitch_rotor = s_cx[1]*cx
        
        self.num_blades_stator = 2*np.pi*rm/self.pitch_stator
        self.num_blades_rotor = 2*np.pi*rm/self.pitch_rotor
        
        self.Omega = Omega
        self.Po1 = Po1
        self.To1 = To1
        
        self.chi = np.stack((self.free_vortex_vane(self.rh,self.rc,self.rm),
                             self.free_vortex_blade(self.rh,self.rc,self.rm)
                             ))

    def get_non_dim_geometry(self,
                             Omega=None,
                             To1=None,
                             Po1=None):
        if self.no_points > 1:
            sys.exit('Currently only set up for one design at a time')
        
        if (To1!=None) and (Po1!=None) and (Omega!=None):
           self.Omega = Omega
           self.To1 = To1
           self.Po1 = Po1
      
        
        #need to set up for dimensional geometry too, to do this just need to have inputs
            
        self.get_stagger()
        self.get_s_cx()
        self.get_t_ps()
        self.get_t_ss()
        self.get_max_t_loc_ps()
        self.get_max_t_loc_ss()
        self.get_recamber_te()
        self.get_lean()
        self.get_beta()
        self.get_loss_rat()
        
        self.eta = 100 - 100*self.get_eta_lost()
        
        mean_line = {"phi": float(self.phi),
                     "psi": float(self.psi),
                     "Lam": float(self.Lambda),
                     "Al1": float(self.Al1),
                     "Ma2": float(self.M2),
                     "eta": float(self.eta),
                     "ga": float(self.ga),
                     "loss_split": float(self.loss_rat),
                     "fc": [0.0,
                            0.0],
                     "TRc": [0.5,
                             0.5]
                     }
        
        bcond = {"To1": float(self.To1),
                 "Po1": float(self.Po1),
                 "rgas": float(self.Rgas),
                 "Omega": float(self.Omega),
                 "delta": float(self.delta)
                 }
        
        threeD = {"htr": float(self.htr),
                  "Re": float(self.Re),
                  "tau_c": 0.0,
                  "Co": [float(self.Co),
                         float(self.Co)],
                  "AR": self.AR
                  }
        
        sect_row_0 = {'tte':float(self.tte),
                           'sect_0': {
                               'spf':float(self.spf_stator),
                               'stagger':float(self.stagger_stator),
                               'recamber':[float(self.recamber_le_stator),
                                           float(self.recamber_te_stator)],
                               'Rle':float(self.Rle_stator),
                               'beta':float(self.beta_stator),
                               "thickness_ps": float(self.t_ps_stator),
                               "thickness_ss": float(self.t_ss_stator),
                               "max_thickness_location_ss": float(self.max_t_loc_ss_stator),
                               "max_thickness_location_ps": float(self.max_t_loc_ps_stator),
                               "lean": float(self.lean_stator)
                               }
                           }
        
        sect_row_1 = {'tte':float(self.tte),
                           'sect_0': {
                               'spf':float(self.spf_rotor),
                               'stagger':float(self.stagger_rotor),
                               'recamber':[float(self.recamber_le_rotor),
                                           float(self.recamber_te_rotor)],
                               'Rle':float(self.Rle_rotor),
                               'beta':float(self.beta_rotor),
                               "thickness_ps": float(self.t_ps_rotor),
                               "thickness_ss": float(self.t_ss_rotor),
                               "max_thickness_location_ss": float(self.max_t_loc_ss_rotor),
                               "max_thickness_location_ps": float(self.max_t_loc_ps_rotor),
                               "lean": float(self.lean_rotor)
                               }
                           }

        with open('turbine_design/turbine_json/datum.json') as f:
            turbine_json = json.load(f)

        turbine_json["mean-line"] = mean_line
        turbine_json['bcond'] = bcond
        turbine_json['3d'] = threeD
        turbine_json['sect_row_0'] = sect_row_0
        turbine_json['sect_row_1'] = sect_row_1
        
        with open('turbine_design/turbine_json/turbine_params.json', 'w') as f:
            json.dump(turbine_json,
                      f, 
                      indent=4)
        
        