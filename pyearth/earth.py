from pyearth._forward import ForwardPasser
from pyearth._pruning import PruningPasser
from pyearth._util import ascii_table, gcv, apply_weights_2d, apply_weights_1d

import numpy as np

class Earth(object):
    '''
    Multivariate Adaptive Regression Splines
    
    A flexible regression method that automatically searches for interactions and non-linear 
    relationships.  Earth models can be thought of as linear models in a higher dimensional 
    basis space (specifically, a multivariate truncated power spline basis).  Each term in an 
    Earth model is a product of so called "hinge functions".  A hinge function is a function 
    that's equal to its argument where that argument is greater than zero and is zero everywhere 
    else.
    
    The multivariate adaptive regression splines algorithm has two stages.  First, the 
    forward pass searches for terms in the truncated power spline basis that locally minimize 
    the squared error loss of the training set.  Next, a pruning pass selects a subset of those 
    terms that produces a locally minimal generalized cross-validation (GCV) score.  The GCV 
    score is not actually based on cross-validation, but rather is meant to approximate a true
    cross-validation score by penalizing model complexity.  The final result is a set of terms
    that is nonlinear in the original feature space, may include interactions, and is likely to 
    generalize well.
    
    The Earth class supports dense input only.  Data structures from the pandas and patsy 
    modules are supported, but are copied into numpy arrays for computation.  No copy is 
    made if the inputs are numpy float64 arrays.  Earth objects can be serialized using the 
    pickle module and copied using the copy module.
    
    
    Parameters
    ----------
    max_terms : int, optional (default=2*n + 10, where n is the number of features)
        The maximum number of terms generated by the forward pass.
    
    
    max_degree : int, optional (default=1)
        The maximum degree of terms generated by the forward pass.
    
    
    penalty : float, optional (default=3.0)
        A smoothing parameter used to calculate GCV and GRSQ.  Used during the pruning pass 
        and to determine whether to add a hinge or linear basis function during the forward
        pass.  See the d parameter in equation 32, Friedman, 1991.
    
    
    endspan_alpha : float, optional, probability between 0 and 1 (default=0.05)
        A parameter controlling the calculation of the endspan parameter (below).  The 
        endspan parameter is calculated as round(3 - log2(endspan_alpha/n)), where n is the
        number of features.  The endspan_alpha parameter represents the probability of a run 
        of positive or negative error values on either end of the data vector of any feature
        in the data set.  See equation 45, Friedman, 1991.
    
    
    endspan : int, optional (default=-1)
        The number of extreme data values of each feature not eligible as knot locations.  
        If endspan is set to -1 (default) then the endspan parameter is calculated based on
        endspan_alpah (above).  If endspan is set to a positive integer then endspan_alpha 
        is ignored.
    
    
    minspan_alpha : float, optional, probability between 0 and 1 (default=0.05)
        A parameter controlling the calculation of the minspan parameter (below).  The 
        minspan parameter is calculated as 
            
            (int) -log2(-(1.0/(n*count))*log(1.0-minspan_alpha)) / 2.5
        
        where n is the number of features and count is the number of points at which the
        parent term is non-zero.  The minspan_alpha parameter represents the probability of 
        a run of positive or negative error values between adjacent knots separated by 
        minspan intervening data points.  See equation 43, Friedman, 1991.
    
    
    minspan : int, optional (default=-1)
        The minimal number of data points between knots.  If minspan is set to -1 (default) 
        then the minspan parameter is calculated based on minspan_alpha (above).  If minspan
        is set to a positive integer then minspan_alpha is ignored.
    
    
    thresh : float, optional (defaul=0.001)
        Parameter used when evaluating stopping conditions for the forward pass.  If either
        RSQ > 1 - thresh or if RSQ increases by less than thresh for a forward pass iteration
        then the forward pass is terminated.
    
    
    min_searh_points : int, optional (default=100)
        Used to calculate check_every (below).  The minimum samples necessary for check_every 
        to be greater than 1.  The check_every parameter is calculated as
        
             (int) m / min_search_points
             
        if m > min_search_points, where m is the number of samples in the training set.  If 
        m <= min_search_points then check_every is set to 1.
    
    
    check_every : int, optional (default=-1)
        If check_every > 0, only one of every check_every sorted data points is considered as 
        a candidate knot.  If check_every is set to -1 then the check_every parameter is 
        calculated based on min_search_points (above).
    
    
    linvars : iterable of strings or ints, optional (empty by default)
        Used to specify features that may only enter terms as linear basis functions (without 
        knots).  Can include both column numbers an column names (see xlabels, below).
    
    
    xlabels : iterable of strings, optional (empty by default)
        The xlabels argument can be used to assign names to data columns.  This argument is not
        generally needed, as names can be captured automatically from most standard data 
        structures.  If included, must have length n, where n is the number of features.  Note 
        that column order is used to compute term values and make predictions, not column names.  
    
    
    Attributes
    ----------
    `coef_` : array, shape = [pruned basis length]
        The weights of the model terms that have not been pruned.
        
        
    `basis_` : _basis.Basis
        An object representing model terms.  Each term is a product of constant, linear, and hinge
        functions of the input features.  
        
    
    `forward_pass_record_` : _record.ForwardPassRecord
        An object containing information about the forward pass, such as training loss function 
        values after each iteration and the final stopping condition.
    
    
    `pruning_pass_record` : _record.PruningPassRecord
        An object containing information about the pruning pass, such as training loss function
        values after each iteration and the selected optimal iteration.

    
    **References:**
    Friedman, Jerome. Multivariate Adaptive Regression Splines.  Annals of Statistics. Volume 19, 
        Number 1 (1991), 1-67.
    
    '''
    
    forward_pass_arg_names = set(['endspan','minspan','endspan_alpha','minspan_alpha',
                                  'max_terms','max_degree','thresh','penalty','check_every',
                                  'min_searh_points','xlabels','linvars'])
    pruning_pass_arg_names = set(['penalty'])
    
    def __init__(self, **kwargs):
        self.set_params(**kwargs)
        
    def __eq__(self, other):
        if self.__class__ is not other.__class__:
            return False
        keys = set(self.__dict__.keys() + other.__dict__.keys())
        for k in keys:
            try:
                v_self = self.__dict__[k]
                v_other = other.__dict__[k]
            except KeyError:
                return False
            try:
                if v_self != v_other:
                    return False
            except ValueError:#Case of numpy arrays
                if np.any(v_self != v_other):
                    return False
        return True
                
    def _pull_forward_args(self, **kwargs):
        '''
        Pull named arguments relevant to the forward pass.
        '''
        result = {}
        for name in self.forward_pass_arg_names:
            if name in kwargs:
                result[name] = kwargs[name]
        return result
    
    def _pull_pruning_args(self, **kwargs):
        '''
        Pull named arguments relevant to the pruning pass.
        '''
        result = {}
        for name in self.pruning_pass_arg_names:
            if name in kwargs:
                result[name] = kwargs[name]
        return result
    
    def _pull_unknown_args(self, **kwargs):
        '''
        Pull unknown named arguments.  Usually an exception is raised if any are 
        actually found, but raising exceptions is the responsibility of the caller.
        '''
        result = {}
        known_args = self.forward_pass_arg_names | self.pruning_pass_arg_names
        for name in kwargs.iterkeys():
            if name not in known_args:
                result[name] = kwargs[name]
        return result
    
    def _scrub_x(self, X, **kwargs):
        '''
        Sanitize input predictors and extract column names if appropriate.
        '''
        no_labels = False
        if 'xlabels' not in kwargs and 'xlabels' not in self.__dict__:
            #Try to get xlabels from input data (for example, if X is a pandas DataFrame)
            try:
                self.xlabels = list(X.columns)
            except AttributeError:
                try:
                    self.xlabels = list(X.design_info.column_names)
                except AttributeError:
                    try:
                        self.xlabels = list(X.dtype.names)
                    except TypeError:
                        no_labels = True
        elif 'xlabels' not in self.__dict__:
            self.xlabels = kwargs['xlabels']
        
        #Convert to internally used data type
        X = np.asarray(X,dtype=np.float64)
        m,n = X.shape
        
        #Make up labels if none were found
        if no_labels:
            self.xlabels = ['x'+str(i) for i in range(n)]
            
        return X
    
    def _scrub(self, X, y, weights, **kwargs):
        '''
        Sanitize input data.
        '''
        #Check whether X is the output of patsy.dmatrices
        if y is None and type(X) is tuple:
            y, X = X
        
        #Handle X separately
        X = self._scrub_x(X, **kwargs)
        
        #Convert y to internally used data type
        y = np.asarray(y,dtype=np.float64)
        y = y.reshape(y.shape[0])
        
        #Deal with weights
        if weights is None:
            weights = np.ones(y.shape[0], dtype=y.dtype)
        else:
            weights = np.asarray(weights)
            weights = weights.reshape(weights.shape[0])
        
        #Make sure dimensions match
        if y.shape[0] != X.shape[0]:
            raise ValueError('X and y do not have compatible dimensions.')
        if y.shape != weights.shape:
            raise ValueError('y and weights do not have compatible dimensions.')
        
        return X, y, weights
    
    def set_params(self, **kwargs):
        '''
        Set or change parameters of an Earth object after its creation.  See Earth class for
        available parameters.
        '''
        #Check for unknown arguments
        unknown_args = self._pull_unknown_args(**kwargs)
        if unknown_args:
            msg = 'Unknown arguments: '
            for i, (k, v) in enumerate(unknown_args.iteritems()):
                msg += k+': '+str(v)
                if i < len(unknown_args) - 1:
                    msg += ', '
                else:
                    msg += '.'
            raise ValueError(msg)
        
        #Process forward pass arguments
        self.__dict__.update(self._pull_forward_args(**kwargs))
        
        #Process pruning pass arguments
        self.__dict__.update(self._pull_pruning_args(**kwargs))
    
    def get_params(self, deep=False):
        '''
        Get any non-default user selected parameter values from the Earth object.
        '''
        result = {}
        result.update(self._pull_forward_args(**self.__dict__))
        result.update(self._pull_pruning_args(**self.__dict__))
        return result
    
    def fit(self, X, y = None, weights=None, xlabels=None, linvars=None):
        '''
        Fit an Earth model to the input data X and y.
        
        
        Parameters
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, a patsy 
            DesignMatrix, or a tuple of patsy DesignMatrix objects as output by patsy.dmatrices.
            
        
        y : array-like, optional (default=None), shape = [m] where m is the number of samples
            The training response.  The y parameter can be a numpy array, a pandas DataFrame with one 
            column, a Patsy DesignMatrix, or can be left as None (default) if X was the output of a 
            call to patsy.dmatrices (in which case, X contains the response).
            
            
        weights : array-like, optional (default=None), shape = [m] where m is the number of samples
            Sample weights for training.  Weights must be greater than or equal to zero.  Rows with 
            greater weights contribute more strongly to the fitted model.  Rows with zero weight do
            not contribute at all.  Weights are useful when dealing with heteroscedasticity.  In such
            cases, the weight should be proportional to the inverse of the (known) variance.
            
            
        xlabels : iterable of strings, optional (default=None)
            Convenient way to set the xlabels parameter while calling fit.  Ignored if None (default).  
            See the Earth class for an explanation of the xlabels parameter.
            
        
        linvars : iterable of ints or strings or both, optional (default=None)
            Convenient way to set the linvars parameter while calling fit.  Ignored if None (default).  
            See the Earth class for an explanation of the linvars parameter.
            
        '''
        #Format and label the data
        if xlabels is not None:
            self.set_params(xlabels=xlabels)
        if linvars is not None:
            self.set_params(linvars=linvars)
        X, y, weights = self._scrub(X,y,weights,**self.__dict__)
        
        #Do the actual work
        self.forward_pass(X, y, weights)
        self.pruning_pass(X, y, weights)
        self.linear_fit(X, y, weights)
        return self
    
    def forward_pass(self, X, y = None, weights = None, **kwargs):
        '''
        Perform the forward pass of the multivariate adaptive regression splines algorithm.  Users
        will normally want to call the fit method instead, which performs the forward pass, the pruning 
        pass, and a linear fit to determine the final model coefficients.
        
        
        Parameters 
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, a patsy 
            DesignMatrix, or a tuple of patsy DesignMatrix objects as output by patsy.dmatrices.
            
        
        y : array-like, optional (default=None), shape = [m] where m is the number of samples
            The training response.  The y parameter can be a numpy array, a pandas DataFrame with one 
            column, a Patsy DesignMatrix, or can be left as None (default) if X was the output of a 
            call to patsy.dmatrices (in which case, X contains the response).
        
        
        weights : array-like, optional (default=None), shape = [m] where m is the number of samples
            Sample weights for training.  Weights must be greater than or equal to zero.  Rows with 
            greater weights contribute more strongly to the fitted model.  Rows with zero weight do
            not contribute at all.  Weights are useful when dealing with heteroscedasticity.  In such
            cases, the weight should be proportional to the inverse of the (known) variance.
            
            
        xlabels : iterable of strings, optional (default=None)
            Convenient way to set the xlabels parameter while calling forward_pass.  Ignored if None 
            (default).  See the Earth class for an explanation of the xlabels parameter.
            
        
        linvars : iterable of ints or strings or both, optional (default=None)
            Convenient way to set the linvars parameter while calling forward_pass.  Ignored if None 
            (default).  See the Earth class for an explanation of the linvars parameter.
            
        
        Note
        ----
        The forward_pass method accepts all other named parameters listed in Earth.forward_pass_arg_names. 
        Passing these parameters to the forward_pass method sets them only for this call, and does not
        change the parameters of the Earth object itself.  To change the parameters of the object 
        itself, use the set_params method.
        
        '''
        
        #Pull new labels and linear variables if necessary
        if 'xlabels' in kwargs and 'xlabels' not in self.__dict__:
            self.set_params(xlabels=kwargs['xlabels'])
            del kwargs['xlabels']
        if 'linvars' in kwargs and 'linvars' not in self.__dict__:
            self.set_params(linvars=kwargs['linvars'])
            del kwargs['linvars']
        
        #Label and format data
        X, y, weights = self._scrub(X,y,weights,**self.__dict__)
         
        #Check for additional forward pass arguments, and fail if someone tried
        #to use other arguments
        args = self._pull_forward_args(**self.__dict__)
        new_args = self._pull_forward_args(**kwargs)
        if len(new_args) < len(kwargs):
            msg = 'Invalid forward pass arguments: '
            for k, v in kwargs.iteritems():
                if k in new_args:
                    continue
                msg += k+': '+str(v) + ','
            msg = msg[0:-1]+'.'
            raise ValueError(msg)
        args.update(new_args)

        #Do the actual work
        args = self._pull_forward_args(**self.__dict__)
        forward_passer = ForwardPasser(X, y, weights, **args)
        forward_passer.run()
        self.forward_pass_record_ = forward_passer.trace()
        self.basis_ = forward_passer.get_basis()
        
    def pruning_pass(self, X, y = None, weights = None, **kwargs):
        '''
        Perform the pruning pass of the multivariate adaptive regression splines algorithm.  Users
        will normally want to call the fit method instead, which performs the forward pass, the pruning 
        pass, and a linear fit to determine the final model coefficients.
        
        
        Parameters 
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, a patsy 
            DesignMatrix, or a tuple of patsy DesignMatrix objects as output by patsy.dmatrices.
            
        
        y : array-like, optional (default=None), shape = [m] where m is the number of samples
            The training response.  The y parameter can be a numpy array, a pandas DataFrame with one 
            column, a Patsy DesignMatrix, or can be left as None (default) if X was the output of a 
            call to patsy.dmatrices (in which case, X contains the response).
            
            
        weights : array-like, optional (default=None), shape = [m] where m is the number of samples
            Sample weights for training.  Weights must be greater than or equal to zero.  Rows with 
            greater weights contribute more strongly to the fitted model.  Rows with zero weight do
            not contribute at all.  Weights are useful when dealing with heteroscedasticity.  In such
            cases, the weight should be proportional to the inverse of the (known) variance.
            
                
        Note
        ----
        The pruning_pass method accepts all other named parameters listed in Earth.pruning_pass_arg_names. 
        Passing these parameters to the pruning_pass method sets them only for this call, and does not
        change the parameters of the Earth object itself.  To change the parameters of the object 
        itself, use the set_params method.
        '''
        #Format data
        X, y, weights = self._scrub(X,y,weights)
        
        #Check for additional pruning arguments and raise ValueError if other arguments are present
        args = self._pull_pruning_args(**self.__dict__)
        new_args = self._pull_pruning_args(**kwargs)
        if len(new_args) < len(kwargs):
            msg = 'Invalid pruning pass arguments: '
            for k, v in kwargs.iteritems():
                if k in new_args:
                    continue
                msg += k+': '+str(v) + ','
            msg = msg[0:-1]+'.'
            raise ValueError(msg)
        args.update(new_args)
        
        #Do the actual work
        pruning_passer = PruningPasser(self.basis_, X, y, weights, **args)
        pruning_passer.run()
        self.pruning_pass_record_ = pruning_passer.trace()
    
    def unprune(self, X, y = None):
        '''Unprune all pruned basis functions and fit coefficients to X and y using the unpruned basis.'''
        for bf in self.basis_:
            bf.unprune()
        del self.pruning_pass_record_
        self.linear_fit(X, y)
    
    def forward_trace(self):
        '''Return information about the forward pass.'''
        try:
            return self.forward_pass_record_
        except AttributeError:
            return None
        
    def pruning_trace(self):
        '''Return information about the pruning pass.'''
        try:
            return self.pruning_pass_record_
        except AttributeError:
            return None
    
    def trace(self):
        '''Return information about the forward and pruning passes.'''
        return EarthTrace(self.forward_trace(),self.pruning_trace())
    
    def summary(self):
        '''Return a string describing the model.'''
        result = ''
        if self.forward_trace() is None:
            result += 'Untrained Earth Model'
            return result
        elif self.pruning_trace() is None:
            result += 'Unpruned Earth Model\n'
        else:
            result += 'Earth Model\n'
        header = ['Basis Function', 'Pruned', 'Coefficient']
        data = []
        i = 0
        for bf in self.basis_:
            data.append([str(bf),'Yes' if bf.is_pruned() else 'No','%g'%self.coef_[i] if not bf.is_pruned() else 'None'])
            if not bf.is_pruned():
                i += 1
        result += ascii_table(header,data)
        if self.pruning_trace() is not None:
            record = self.pruning_trace()
            selection = record.get_selected()
        else:
            record = self.forward_trace()
            selection = len(record) - 1
        result += '\n'
        result += 'MSE: %.4f, GCV: %.4f, RSQ: %.4f, GRSQ: %.4f' % (record.mse(selection), record.gcv(selection), record.rsq(selection), record.grsq(selection))
        return result
    
    def linear_fit(self, X, y = None, weights = None):
        '''
        Solve the linear least squares problem to determine the coefficients of the unpruned basis functions.
        
        
        Parameters 
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, a patsy 
            DesignMatrix, or a tuple of patsy DesignMatrix objects as output by patsy.dmatrices.
            
        
        y : array-like, optional (default=None), shape = [m] where m is the number of samples
            The training response.  The y parameter can be a numpy array, a pandas DataFrame with one 
            column, a Patsy DesignMatrix, or can be left as None (default) if X was the output of a 
            call to patsy.dmatrices (in which case, X contains the response).
            
            
        weights : array-like, optional (default=None), shape = [m] where m is the number of samples
            Sample weights for training.  Weights must be greater than or equal to zero.  Rows with 
            greater weights contribute more strongly to the fitted model.  Rows with zero weight do
            not contribute at all.  Weights are useful when dealing with heteroscedasticity.  In such
            cases, the weight should be proportional to the inverse of the (known) variance.
        '''
        
        #Format data
        X, y, weights = self._scrub(X,y,weights)
        
        #Transform into basis space
        B = self.transform(X)
        
        #Apply weights to B
        apply_weights_2d(B,weights)
        
        #Apply weights to y
        weighted_y = y.copy()
        apply_weights_1d(weighted_y,weights)
        
        #Solve the linear least squares problem
        self.coef_ = np.linalg.lstsq(B,weighted_y)[0]
    
    def predict(self, X):
        '''
        Predict the response based on the input data X.
        
        
        Parameters 
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, or a 
            patsy DesignMatrix.

        '''
        X = self._scrub_x(X)
        B = self.transform(X)
        return np.dot(B,self.coef_)
    
    def transform(self, X):
        '''
        Transform X into the basis space.  Normally, users will call the predict method instead, which
        both transforms into basis space calculates the weighted sum of basis terms to produce a 
        prediction of the response.  Users may wish to call transform directly in some cases.  For 
        example, users may wish to apply other statistical or machine learning algorithms, such as 
        generalized linear regression, in basis space.
        
        
        Parameters 
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, or a 
            patsy DesignMatrix.
        '''
        X = self._scrub_x(X)
        B = np.empty(shape=(X.shape[0],self.basis_.plen()))
        self.basis_.transform(X,B)
        return B
    
    def get_penalty(self):
        '''Get the penalty parameter being used.  Default is 3.'''
        if 'penalty' in self.__dict__ and self.penalty is not None:
            return self.penalty
        else:
            return 3.0
    
    def score(self, X, y = None):
        '''
        Calculate the generalized r^2 of the model on data X and y.
        
        
        Parameters 
        ----------
        X : array-like, shape = [m, n] where m is the number of samples and n is the number of features
            The training predictors.  The X parameter can be a numpy array, a pandas DataFrame, a patsy 
            DesignMatrix, or a tuple of patsy DesignMatrix objects as output by patsy.dmatrices.
            
        
        y : array-like, optional (default=None), shape = [m] where m is the number of samples
            The training response.  The y parameter can be a numpy array, a pandas DataFrame with one 
            column, a Patsy DesignMatrix, or can be left as None (default) if X was the output of a 
            call to patsy.dmatrices (in which case, X contains the response).
        '''
        X, y, _ = self._scrub(X, y, None)
        y_hat = self.predict(X)
        m, n = X.shape
        residual = y-y_hat
        mse = np.sum(residual**2) / m
        mse0 = np.sum((y - np.mean(y))**2) / m
        gcv0 = gcv(mse0,1,m,self.get_penalty())
        gcv_ = gcv(mse,self.basis_.plen(),m,self.get_penalty())
        return 1 - (gcv_/gcv0)

    def __repr__(self):
        result = 'Earth('
        first = True
        for k, v in self.get_params().iteritems():
            if not first:
                result += ', '
            else:
                first = False
            result += '%s=%s' % (str(k), str(v))
        result += ')'
        return result
    
    def __str__(self):
        return self.__repr__()

class EarthTrace(object):
    def __init__(self, forward_trace, pruning_trace):
        self.forward_trace = forward_trace
        self.pruning_trace = pruning_trace
        
    def __eq__(self, other):
        return self.__class__ is other.__class__ and self.forward_trace == other.forward_trace and \
            self.pruning_trace == other.pruning_trace
        
    def __str__(self):
        return str(self.forward_trace) + '\n' + str(self.pruning_trace)
    
