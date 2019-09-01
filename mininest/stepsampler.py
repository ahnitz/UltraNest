"""

MCMC-like step sampling within a region

"""


import numpy as np

def generate_random_direction(ui, region, scale=1):
    v = np.random.normal(0, 1, size=len(ui))
    v *= scale / (v**2).sum()**0.5
    return v

def generate_cube_oriented_direction(ui, region):
    ndim = len(ui)
    # choose axis
    j = np.random.randint(ndim)
    # use doubling procedure to identify left and right maxima borders
    v = np.zeros(ndim)
    v[j] = 1.0
    return v


def generate_region_oriented_direction(ui, region, scale=1):
    ndim = len(ui)
    ti = region.transformLayer.transform(ui)
    
    # choose axis in transformed space:
    j = np.random.randint(ndim)
    tv = np.zeros(ndim)
    tv[j] = 1.0
    # convert back to unit cube space:
    uj = region.transformLayer.untransform(ti + tv * 1e-3)
    v = uj - ui
    v *= scale / (v**2).sum()**0.5
    return v

def generate_region_random_direction(ui, region, scale=1):
    ti = region.transformLayer.transform(ui)
    
    # choose axis in transformed space:
    ti = np.random.normal(ti, 1)
    #ti *= scale / (ti**2).sum()**0.5
    # convert back to unit cube space:
    uj = region.transformLayer.untransform(ti)
    v = uj - ui
    v *= scale / (v**2).sum()**0.5
    return v


class StepSampler(object):
    """
    Simple step sampler, staggering around
    Scales proposal towards a 50% acceptance rate
    """
    def __init__(self, nsteps):
        """
        nsteps: int
            number of accepted steps until the sample is considered independent
        """
        self.history = []
        self.nsteps = nsteps
        self.nrejects = 0
        self.scale = 1.0
        self.last = None, None
        self.logstat = []
        self.logstat_labels = ['accepted', 'scale']
    
    def __str__(self):
        return type(self).__name__ + '(%d steps)' % self.nsteps
    
    def plot(self, filename):
        if len(self.logstat) == 0:
            return
        
        parts = np.transpose(self.logstat)
        plt.figure(figsize=(10, 1+3*len(parts)))
        for i, (label, part) in enumerate(zip(self.logstat_labels, parts)):
            plt.subplot(len(parts), 1, 1+i)
            plt.ylabel(label)
            plt.plot(part)
            if np.min(part) > 0:
                plt.yscale('log')
        plt.savefig(filename, bbox_inches='tight')
        plt.close()
    
    def move(self, ui, region, ndraw=1, plot=False):
        raise NotImplementedError()
    
    def adjust_outside_region(self):
        #print("ineffective proposal scale (%e). shrinking..." % self.scale)
        self.scale *= 0.1
        assert self.scale > 0
        self.last = None, None
        self.logstat.append([False, self.scale])
    
    def adjust_accept(self, accepted, unew, pnew, Lnew, nc):
        if accepted:
            self.scale *= 1.04
            self.last = unew, Lnew
            self.history.append((unew, Lnew))
        else:
            self.scale /= 1.04
            self.nrejects += 1
        self.logstat.append([accepted, self.scale])
    
    def reset(self):
        self.nrejects = 0

    def __next__(self, region, Lmin, us, Ls, transform, loglike, ndraw=40, plot=False):
        
        # find most recent point in history conforming to current Lmin
        ui, Li = self.last
        if Li is not None and not Li >= Lmin:
            #print("wandered out of L constraint; resetting", ui[0])
            ui, Li = None, None
        
        if Li is not None and not region.inside(ui.reshape((1,-1))):
            # region was updated and we are not inside anymore 
            # so reset
            ui, Li = None, None
        
        if Li is None and self.history:
            # try to resume from a previous point above the current contour
            for uj, Lj in self.history[::-1]:
                if Lj >= Lmin and region.inside(uj.reshape((1,-1))):
                    ui, Li = uj, Lj
                    break
        
        # select starting point
        if Li is None:
            # choose a new random starting point
            mask = region.inside(us)
            assert mask.any(), ("None of the live points satisfies the current region!", 
                region.maxradiussq, region.u, region.unormed, us)
            i = np.random.randint(mask.sum())
            self.starti = i
            ui = us[mask,:][i]
            #print("starting at", ui[0])
            assert np.logical_and(ui > 0, ui < 1).all(), ui
            Li = Ls[mask][i]
            self.reset()
            self.history.append((ui, Li))
        
        unew = self.move(ui, region, ndraw=ndraw, plot=plot)
        if plot:
            plt.plot([ui[0], unew[:,0]], [ui[1], unew[:,1]], '-', color='k', lw=0.5)
            plt.plot(ui[0], ui[1], 'd', color='r', ms=4)
            plt.plot(unew[:,0], unew[:,1], 'x', color='r', ms=4)
        mask = np.logical_and(unew > 0, unew < 1).all(axis=1)
        unew = unew[mask,:]
        mask = region.inside(unew)
        nc = 0
        
        if mask.any():
            i = np.where(mask)[0][0]
            unew = unew[i,:]
            pnew = transform(unew)
            Lnew = loglike(pnew)
            nc = 1
            if Lnew >= Lmin:
                if plot:
                    plt.plot(unew[0], unew[1], 'o', color='g', ms=4)
                self.adjust_accept(True, unew, pnew, Lnew, nc)
                if len(self.history) >= self.nsteps:
                    #print("made %d steps" % len(self.history))
                    self.history = []
                    self.last = None, None
                    return unew, pnew, Lnew, nc
            else:
                self.adjust_accept(False, unew, pnew, Lnew, nc)
        else:
            self.adjust_outside_region()
        
        # do not have a independent sample yet
        return None, None, None, nc

class CubeMHSampler(StepSampler):
    """
    Simple step sampler, staggering around
    """
    def move(self, ui, region, ndraw=1, plot=False):
        # propose in that direction
        jitter = np.random.normal(0, 1, size=(ndraw, len(ui))) * self.scale
        unew = ui.reshape((1, -1)) + jitter
        return unew

class RegionMHSampler(StepSampler):
    """
    Simple step sampler, staggering around
    """
    def move(self, ui, region, ndraw=1, plot=False):
        ti = region.transformLayer.transform(ui)
        jitter = np.random.normal(0, 1, size=(ndraw, len(ui))) * self.scale
        tnew = ti.reshape((1, -1)) + jitter
        unew = region.transformLayer.untransform(tnew)
        return unew

class DESampler(StepSampler):
    """
    Simple step sampler using as directions the differences 
    between two randomly chosen live points.
    """
    def move(self, ui, region, ndraw=1, plot=False):
        # choose direction
        # avoid drawing the two exact same points (no direction)
        # avoid drawing the starting point (to avoid linear combinations)
        j = np.random.randint(len(region.u) - 1)
        if j >= self.starti:
            j += 1
        k = np.random.randint(len(region.u) - 2)
        if k >= self.starti:
            k += 1
        if k >= j:
            k += 1
        direction = region.u[j,:] - region.u[k,:]
        assert (direction != 0).all(), (j, k, direction, region.u[j,:], region.u[k,:])
        
        # propose in that direction
        jitter = np.random.normal(0, 1e-4 / len(ui), size=(ndraw, len(ui)))
        direction = direction + jitter * (direction**2).sum()**0.5
        vector = np.random.normal(size=(ndraw, 1)) * direction * self.scale
        unew = ui.reshape((1, -1)) + vector + jitter
        return unew


class CubeSliceSampler(StepSampler):
    """
    Slice sampler, respecting the region
    """
    def __init__(self, nsteps):
        """
        see StepSampler.__init__ documentation
        """
        StepSampler.__init__(self, nsteps=nsteps)
        self.reset()
    
    def reset(self):
        self.interval = None
        self.found_left = False
        self.found_right = False
        self.axis_index = 0

    def generate_direction(self, ui, region):
        return generate_cube_oriented_direction(ui, region)

    def adjust_accept(self, accepted, unew, pnew, Lnew, nc):
        v, left, right, u = self.interval
        if not self.found_left: 
            if accepted:
                self.interval = (v, left * 2, right, u)
            else:
                self.found_left = True
        elif not self.found_right:
            if accepted:
                self.interval = (v, left, right * 2, u)
            else:
                self.found_right = True
                # adjust scale
                if -left > self.scale or right > self.scale:
                    self.scale *= 1.1
                else:
                    self.scale /= 1.1
        else:
            if accepted:
                # start with a new interval next time
                self.interval = None
                
                self.last = unew, Lnew
                self.history.append((unew, Lnew))
            else:
                self.nrejects += 1
                # shrink current interval
                if u == 0:
                    pass
                elif u < 0:
                    left = u
                elif u > 0:
                    right = u
                
                self.interval = (v, left, right, u)
        self.logstat.append([accepted, self.scale])

    def adjust_outside_region(self):
        self.adjust_accept(False, unew=None, pnew=None, Lnew=None, nc=0)
    
    def move(self, ui, region, ndraw=1, plot=False):
        if self.interval is None:
            v = self.generate_direction(ui, region)
            
            # expand direction until it is surely outside
            left = -self.scale
            right = self.scale
            u = 0
            
            self.interval = (v, left, right, u)
            
        else:
            v, left, right, u = self.interval
        
        if plot:
            plt.plot([(ui + v * left)[0], (ui + v * right)[0]], 
                [(ui + v * left)[1], (ui + v * right)[1]],
                ':o', color='k', lw=2, alpha=0.3)
        # shrink direction if outside
        while True:
            if not self.found_left:
                xj = ui + v * left

                if region.inside(xj.reshape((1, -1))):
                    self.interval = (v, left, right, u)
                    return xj.reshape((1, -1))
                else:
                    self.found_left = True

            if not self.found_right:
                xj = ui + v * right
                
                if region.inside(xj.reshape((1, -1))):
                    self.interval = (v, left, right * 2, u)
                    return xj.reshape((1, -1))
                else:
                    self.found_right = True
            
            u = np.random.uniform(left, right)
            xj = ui + v * u
            
            if region.inside(xj.reshape((1, -1))):
                self.interval = (v, left, right, u)
                return xj.reshape((1, -1))
            else:
                if u < 0:
                    left = u
                else:
                    right = u
                self.interval = (v, left, right, u)


class RegionSliceSampler(CubeSliceSampler):
    """
    Slice sampler, in region axes
    """
    def generate_direction(self, ui, region):
        return generate_region_oriented_direction(ui, region)


class RegionSequentialSliceSampler(CubeSliceSampler):
    """
    Slice sampler, in region axes
    """
    def generate_direction(self, ui, region, scale=1):
        ndim = len(ui)
        ti = region.transformLayer.transform(ui)
        
        # choose axis in transformed space:
        j = self.axis_index % ndim
        self.axis_index = j + 1
        tv = np.zeros(ndim)
        tv[j] = 1.0
        # convert back to unit cube space:
        uj = region.transformLayer.untransform(ti + tv * 1e-3)
        v = uj - ui
        v *= scale / (v**2).sum()**0.5
        return v



class RegionBallSliceSampler(CubeSliceSampler):
    """
    Slice sampler, in random directions according to region
    """
    def generate_direction(self, ui, region):
        return generate_region_random_direction(ui, region)



from mininest.samplingpath import SamplingPath, ContourSamplingPath, extrapolate_ahead
import matplotlib.pyplot as plt

class SamplingPathSliceSampler(StepSampler):
    """
    Slice sampler, respecting the region, on the sampling path
    """
    def __init__(self, nsteps):
        """
        see StepSampler.__init__ documentation
        """
        StepSampler.__init__(self, nsteps=nsteps)
        self.interval = None
        self.path = None

    def generate_direction(self, ui, region, scale=1):
        return generate_region_oriented_direction(ui, region, scale=scale)

    def adjust_accept(self, accepted, unew, pnew, Lnew, nc):
        if accepted:
            # start with a new interval next time
            self.interval = None
            
            self.last = unew, Lnew
            self.history.append((unew, Lnew))
        else:
            self.nrejects += 1
            # continue on current interval
            pass
        self.logstat.append([accepted, self.scale])

    def adjust_outside_region(self):
        self.logstat.append([False, self.scale])
    
    def move(self, ui, region, ndraw=1, plot=False):
        if self.interval is None:
            v = self.generate_direction(ui, region, scale=self.scale)
            self.path = ContourSamplingPath(SamplingPath(ui, v, 0.0), 
                region)
            
            if not (ui > 0).all() or not (ui < 1).all() or not region.inside(ui.reshape((1, -1))):
                assert False, ui
            
            # unit hypercube diagonal gives a reasonable maximum path length
            maxlength = len(ui)**0.5
            
            # expand direction until it is surely outside
            left = -1
            right = +1
            while abs(left*self.scale) < maxlength:
                xj, vj = self.path.extrapolate(left)
                if not (xj > 0).all() or not (xj < 1).all() or not region.inside(xj.reshape((1, -1))):
                    break
                #self.path.add(left, xj, vj, 0.0)
                left *= 2
            
            while abs(right * self.scale) < maxlength:
                xj, _ = self.path.extrapolate(right)
                if not (xj > 0).all() or not (xj < 1).all() or not region.inside(xj.reshape((1, -1))):
                    break
                #self.path.add(right, xj, vj, 0.0)
                right *= 2
            
            scale = max(-left, right)
            #print("scale %f gave %d %d " % (self.scale, left, right))
            if scale < 5:
                self.scale /= 1.1
            #if scale > 100:
            #    self.scale *= 1.1
            
            assert self.scale > 1e-10, self.scale
            self.interval = (left, right, None)
        else:
            left, right, mid = self.interval
            # we rejected mid, and shrink corresponding side
            if mid < 0:
                left = mid
            elif mid > 0:
                right = mid
        
        # shrink direction if outside
        while True:
            mid = np.random.randint(left, right + 1)
            #print("interpolating %d - %d - %d" % (left, mid, right), 
            #    self.path.points)
            if mid == 0:
                _, xj, _, _ = self.path.points[0]
            else:
                xj, _ = self.path.extrapolate(mid)
            
            if region.inside(xj.reshape((1, -1))):
                self.interval = (left, right, mid)
                return xj.reshape((1, -1))
            else:
                if mid < 0:
                    left = mid
                else:
                    right = mid
                self.interval = (left, right, mid)


class SamplingPathStepSampler(StepSampler):
    """
    Step sampler on a sampling path
    """
    def __init__(self, nresets, nsteps, scale=1.0, balance=0.01, nudge=1.1, log=False):
        """
        nresets: int
            after this many iterations, select a new direction
        nsteps: int
            how many steps to make in total
        scale: float
            initial step size
        balance: float
            acceptance rate to target
            if below, scale is increased, if above, scale is decreased
        nudge: float
            factor for increasing scale (must be >=1)
            nudge=1 implies no step size adaptation.
        """
        StepSampler.__init__(self, nsteps=nsteps)
        #self.lasti = None
        self.path = None
        self.nresets = nresets
        # initial step scale in transformed space
        self.scale = scale
        # fraction of times a reject is expected
        self.balance = balance
        # relative increase in step scale
        self.nudge = nudge
        assert nudge >= 1
        self.log = log
        self.grad_function = None
        self.istep = 0
        self.iresets = 0
        self.start()
        self.terminate_path()
        self.logstat_labels = ['acceptance rate', 'reflection rate', 'scale', 'nstuck']

    def __str__(self):
        return type(self).__name__ + '(%d steps, %d resets, AR=%d%%)' % (self.nsteps, self.nresets, (1-self.balance)*100)
    
    def start(self):
        if hasattr(self, 'naccepts') and self.nrejects + self.naccepts > 0:
            self.logstat.append([self.naccepts / (self.nrejects + self.naccepts), 
                self.nreflects / (self.nreflects + self.nrejects + self.naccepts), 
                self.scale, self.nstuck])
        self.nrejects = 0
        self.naccepts = 0
        self.nreflects = 0
        self.nstuck = 0
        self.istep = 0
        self.iresets = 0
        self.noutside_regions = 0
        self.last = None, None
        self.history = []

        self.direction = +1
        self.deadends = set()
        self.path = None
    
    def start_path(self, ui, region):
        #print("new direction:", self.scale, self.noutside_regions, self.nrejects, self.naccepts)
        
        v = self.generate_direction(ui, region, scale=self.scale)
        assert (v**2).sum() > 0, (v, self.scale)
        assert region.inside(ui.reshape((1, -1))).all(), ui
        self.path = ContourSamplingPath(SamplingPath(ui, v, 0.0), region)
        if self.grad_function is not None:
            self.path.gradient = self.grad_function
        
        if not (ui > 0).all() or not (ui < 1).all() or not region.inside(ui.reshape((1, -1))):
            assert False, ui
        
        self.direction = +1
        self.lasti = 0
        self.cache = {0: (True, ui, self.last[1])}
        self.deadends = set()
        #self.iresets += 1
        if self.log:
            print()
            print("starting new direction", v, 'from', ui)
    
    def terminate_path(self):
        """ terminate current path, and reset path counting variable """
        
        if -1 in self.deadends and +1 in self.deadends:
            #self.scale /= self.nudge
            self.nstuck += 1
        
        #self.nrejects = 0
        #self.naccepts = 0
        #self.istep = 0
        #self.noutside_regions = 0
        self.direction = +1
        self.deadends = set()
        self.path = None
        self.iresets += 1
        if self.log:
            print("reset %d" % self.iresets)
    
    def set_gradient(self, grad_function):
        print("set gradient function to %s" % grad_function.__name__)
        def plot_gradient_wrapper(x, plot=False):
            v = grad_function(x)
            if plot:
                plt.plot(x[0], x[1], '+ ', color='k', ms=10)
                plt.plot([x[0], v[0] * 1e-2 + x[0]], [x[1], v[1] * 1e-2 + x[1]], color='gray')
            return v
        self.grad_function = plot_gradient_wrapper

    def generate_direction(self, ui, region, scale):
        return generate_region_random_direction(ui, region, scale=scale)
        #return generate_random_direction(ui, region, scale=scale)

    def adjust_accept(self, accepted, unew, pnew, Lnew, nc):
        self.cache[self.nexti] = (accepted, unew, Lnew)
        if accepted:
            # start at new point next time
            self.lasti = self.nexti
            self.last = unew, Lnew
            self.history.append((unew, Lnew))
            self.naccepts += 1
        else:
            # continue on current point, do not update self.last
            self.nrejects += 1
            self.history.append((unew, Lnew))
            assert self.scale > 1e-10, (self.scale, self.istep, self.nrejects)

    def adjust_outside_region(self):
        self.noutside_regions += 1
        self.nrejects += 1
    
    def adjust_scale(self, maxlength):
        #print("%2d | %2d | %2d | %2d %2d %2d %2d | %f"  % (self.iresets, self.istep, 
        #    len(self.history), self.naccepts, self.nrejects, 
        #    self.noutside_regions, self.nstuck, self.scale))
        log = self.log
        assert len(self.history) > 1
        
        if self.naccepts < (self.nrejects + self.naccepts) * self.balance:
            if log:
                print("adjusting scale %f down: istep=%d inside=%d outside=%d region=%d nstuck=%d" % (
                    self.scale, len(self.history), self.naccepts, self.nrejects, self.noutside_regions, self.nstuck))
            self.scale /= self.nudge
        else:
            if self.scale < maxlength or True:
                if log:
                    print("adjusting scale %f up: istep=%d inside=%d outside=%d region=%d nstuck=%d" % (
                        self.scale, len(self.history), self.naccepts, self.nrejects, self.noutside_regions, self.nstuck))
                self.scale *= self.nudge
        assert self.scale > 1e-10, self.scale
    
    def movei(self, ui, region, ndraw=1, plot=False):
        if self.path is not None:
            if self.lasti - 1 in self.deadends and self.lasti + 1 in self.deadends:
                # stuck, cannot go anywhere. Stay.
                self.nexti = self.lasti
                return self.nexti
        
        if self.path is None:
            self.start_path(ui, region)
        
        assert not (self.lasti - 1 in self.deadends and self.lasti + 1 in self.deadends), (self.deadends, self.lasti)
        if self.lasti + self.direction in self.deadends:
            self.direction *= -1
        
        self.nexti = self.lasti + self.direction
        #print("movei", self.nexti)
        # self.nexti = self.lasti + np.random.randint(0, 2) * 2 - 1
        return self.nexti

    def move(self, ui, region, ndraw=1, plot=False):
        u, v = self.get_point(self.movei(ui, region=region, ndraw=ndraw, plot=plot))
        return u.reshape((1, -1))

    
    def reflect(self, reflpoint, v, region, plot=False):
        normal = self.path.gradient(reflpoint, plot=plot)
        if normal is None:
            return -v
        return v - 2 * (normal * v).sum() * normal

    def get_point(self, inew):
        ipoints = [(u, v) for i, u, p, v in self.path.points if i == inew]
        if len(ipoints) == 0:
            #print("getting point %d" % inew, self.path.points) #, "->", self.path.extrapolate(self.nexti))
            return self.path.extrapolate(inew)
        else:
            return ipoints[0]
    
    
    def __next__(self, region, Lmin, us, Ls, transform, loglike, ndraw=40, plot=False):
        
        # find most recent point in history conforming to current Lmin
        ui, Li = self.last
        if Li is not None and not Li >= Lmin:
            if self.log:
                print("wandered out of L constraint; resetting", ui[0])
            ui, Li = None, None
        
        if Li is not None and not region.inside(ui.reshape((1,-1))):
            # region was updated and we are not inside anymore 
            # so reset
            if self.log:
                print("region change; resetting")
            ui, Li = None, None
        
        if Li is None and self.history:
            # try to resume from a previous point above the current contour
            for uj, Lj in self.history[::-1]:
                if Lj >= Lmin and region.inside(uj.reshape((1,-1))):
                    ui, Li = uj, Lj
                    if self.log:
                        print("recovered using history", ui)
                    break
            
        
        # select starting point
        if Li is None:
            # choose a new random starting point
            mask = region.inside(us)
            assert mask.any(), ("None of the live points satisfies the current region!", 
                region.maxradiussq, region.u, region.unormed, us)
            i = np.random.randint(mask.sum())
            self.starti = i
            ui = us[mask,:][i]
            if self.log:
                print("starting at", ui)
            assert np.logical_and(ui > 0, ui < 1).all(), ui
            Li = Ls[mask][i]
            self.start()
            self.history.append((ui, Li))
            self.last = (ui, Li)
        
        inew = self.movei(ui, region, ndraw=ndraw)
        if self.log:
            print("i: %d->%d (step %d)" % (self.lasti, inew, self.istep))
            
        #uold, _ = self.get_point(self.lasti)
        _, uold, Lold = self.cache[self.lasti]
        if plot:
            plt.plot(uold[0], uold[1], 'd', color='brown', ms=4)
        
        uret, pret, Lret = uold, transform(uold), Lold
        
        nc = 0
        if inew != self.lasti:
            accept = False
            if inew not in self.cache:
                unew, _ = self.get_point(inew)
                if plot:
                    plt.plot(unew[0], unew[1], 'x', color='k', ms=4)
                accept = np.logical_and(unew > 0, unew < 1).all() and region.inside(unew.reshape((1, -1)))
                if accept:
                    if plot:
                        plt.plot(unew[0], unew[1], '+', color='orange', ms=4)
                    pnew = transform(unew)
                    Lnew = loglike(pnew)
                    nc = 1
                else:
                    Lnew = -np.inf
                    if self.log:
                        print("outside region: ", unew, "from", ui)
                    self.deadends.add(inew)
                    self.adjust_outside_region()
            else:
                _, unew, Lnew = self.cache[self.nexti]
                #if plot:
                #    plt.plot(unew[0], unew[1], 's', color='r', ms=2)
            
            if self.log:
                print("   suggested point:", unew)
            pnew = transform(unew)
            
            if Lnew >= Lmin:
                if self.log:
                    print(" -> inside.")
                if plot:
                    plt.plot(unew[0], unew[1], 'o', color='g', ms=4)
                self.adjust_accept(True, unew, pnew, Lnew, nc)
                uret, pret, Lret = unew, pnew, Lnew
            else:
                if plot:
                    plt.plot(unew[0], unew[1], '+', color='k', ms=2, alpha=0.3)
                if self.log:
                    print(" -> outside.")
                jump_successful = False
                if inew not in self.cache and inew not in self.deadends:
                    # first time we try to go beyond
                    # try to reflect:
                    reflpoint, v = self.get_point(inew)
                    if self.log:
                        print("    trying to reflect at", reflpoint)
                    self.nreflects += 1
                    
                    sign = -1 if inew < 0 else +1
                    vnew = self.reflect(reflpoint, v * sign, region=region) * sign
                    
                    xk, vk = extrapolate_ahead(sign, reflpoint, vnew, contourpath=self.path)
                    
                    if plot:
                        plt.plot([reflpoint[0], (-v + reflpoint)[0]], [reflpoint[1], (-v + reflpoint)[1]], '-', color='k', lw=0.5, alpha=0.5)
                        plt.plot([reflpoint[0], (vnew + reflpoint)[0]], [reflpoint[1], (vnew + reflpoint)[1]], '-', color='k', lw=1)
                    
                    if self.log:
                        print("    trying", xk)
                    accept = np.logical_and(xk > 0, xk < 1).all() and region.inside(xk.reshape((1, -1)))
                    if accept:
                        pk = transform(xk)
                        Lk = loglike(pk)
                        nc += 1
                        if Lk >= Lmin:
                            jump_successful = True
                            uret, pret, Lret = xk, pk, Lk
                            if self.log:
                                print("successful reflect!")
                            self.path.add(inew, xk, vk, Lk)
                            self.adjust_accept(True, xk, pk, Lk, nc)
                        else:
                            if self.log:
                                print("unsuccessful reflect")
                            self.adjust_accept(False, xk, pk, Lk, nc)
                    else:
                        if self.log:
                            print("unsuccessful reflect out of region")
                        self.adjust_outside_region()
                    
                    if plot:
                        plt.plot(xk[0], xk[1], 'x', color='g' if jump_successful else 'r', ms=8)
                    
                    if not jump_successful:
                        # unsuccessful. mark as deadend
                        self.deadends.add(inew)
                        #print("deadends:", self.deadends)
                else:
                    self.adjust_accept(False, uret, pret, Lret, nc)
                
                #self.adjust_accept(False, unew, pnew, Lnew, nc)
                assert inew in self.cache or inew in self.deadends, (inew in self.cache, inew in self.deadends)
        else:
            # stuck, proposal did not move us
            self.nstuck += 1
            self.adjust_accept(False, uret, pret, Lret, nc)
        
        # increase step count
        self.istep += 1
        if self.istep == self.nsteps:
            if self.log:
                print("triggering re-orientation")
                # reset path so we go in a new direction
            self.terminate_path()
            self.istep = 0

        # if had enough resets, return final point
        if self.iresets >= self.nresets:
            if self.log:
                print("walked %d paths; returning sample" % self.iresets)
            self.adjust_scale(maxlength = len(uret)**0.5)
            self.start()
            self.last = None, None
            return uret, pret, Lret, nc
        
        # do not have a independent sample yet
        return None, None, None, nc


from mininest.flatnuts import ClockedStepSampler, ClockedBisectSampler, ClockedNUTSSampler
from mininest.flatnuts import SingleJumper, DirectJumper, IntervalJumper


class OtherSamplerProxy(object):
    """
    Proxy for ClockedSamplers
    """
    def __init__(self, nnewdirections, sampler='steps', nsteps=0, 
            balance=0.9, scale=0.1, nudge=1.1, log=False):
        """
        nsteps: int
            number of accepted steps until the sample is considered independent
        """
        self.nsteps = nsteps
        self.samplername = sampler
        self.sampler = None
        
        self.scale = scale
        self.nudge = nudge
        self.balance = balance
        self.log = log
        
        self.last = None, None
        self.ncalls = 0
        self.nnewdirections = nnewdirections
        self.nreflections = 0
        self.nreverses = 0
        self.nsteps_done = 0
        
        self.naccepts = 0
        self.nrejects = 0

        self.logstat = []
        self.logstat_labels = ['accepted', 'scale']
    
    def __str__(self):
        return 'Proxy[%s](%dx%d steps, AR=%d%%)' % (self.samplername, self.nnewdirections, self.nsteps, self.balance*100)
    
    def accumulate_statistics(self):
        self.nreflections += self.sampler.nreflections
        self.nreverses += self.sampler.nreverses
        points = self.sampler.points
        # range
        ilo, _, _, _ = min(points)
        ihi, _, _, _ = max(points)
        self.nsteps_done += ihi - ilo
        
        self.naccepts += self.stepper.naccepts
        self.nrejects += self.stepper.nrejects
        if self.log: 
            print("%2d direction encountered %2d accepts, %2d rejects"  % (
                self.nrestarts, self.stepper.naccepts, self.stepper.nrejects))
        
    def adjust_scale(self, maxlength):
        log = self.log
        if log: 
            print("%2d | %2d %2d %2d | %f"  % (self.nrestarts,
                self.naccepts, self.nrejects, self.nreflections, self.scale))
        self.logstat.append([self.naccepts / (self.naccepts + self.nrejects), self.scale])
        
        if self.naccepts < (self.nrejects + self.naccepts) * self.balance:
            if log:
                print("adjusting scale %f down" % self.scale)
            self.scale /= self.nudge
        else:
            if self.scale < maxlength or True:
                if log:
                    print("adjusting scale %f up" % self.scale)
                self.scale *= self.nudge
        assert self.scale > 1e-10, self.scale
    
    def startup(self, region, us, Ls):
        # choose a new random starting point
        if self.log: print("starting from scratch...")
        mask = region.inside(us)
        assert mask.all(), ("Not all of the live points satisfy the current region!", 
            region.maxradiussq, region.u[~mask,:], region.unormed[~mask,:], us[~mask,:])
        i = np.random.randint(mask.sum())
        self.starti = i
        ui = us[mask,:][i]
        assert np.logical_and(ui > 0, ui < 1).all(), ui
        Li = Ls[mask][i]
        self.last = ui, Li
        self.ncalls = 0
        self.nrestarts = 0

        self.nreflections = 0
        self.nreverses = 0
        self.nsteps_done = 0
        self.naccepts = 0
        self.nrejects = 0
        
        self.sampler = None
        self.stepper = None
    
    def start_direction(self, region):
        # choose random direction
        if self.log: print("choosing random direction")
        ui, Li = self.last
        #v = generate_random_direction(ui, region, scale=self.scale)
        v = generate_region_random_direction(ui, region, scale=self.scale)
        self.nrestarts += 1
        
        if self.sampler is None or True:
            samplingpath = SamplingPath(ui, v, Li)
            contourpath = ContourSamplingPath(samplingpath, region)
            if self.samplername == 'steps':
                self.sampler = ClockedStepSampler(contourpath)
                self.stepper = DirectJumper(self.sampler, self.nsteps)
            elif self.samplername == 'bisect':
                self.sampler = ClockedBisectSampler(contourpath)
                self.stepper = DirectJumper(self.sampler, self.nsteps)
            elif self.samplername == 'nuts':
                self.sampler = ClockedNUTSSampler(contourpath)
                self.stepper = IntervalJumper(self.sampler, self.nsteps)
            else:
                assert False
    
    def __next__(self, region, Lmin, us, Ls, transform, loglike, ndraw=40, plot=False):
        
        # find most recent point in history conforming to current Lmin
        ui, Li = self.last
        if Li is not None and not Li >= Lmin:
            #print("wandered out of L constraint; resetting", ui[0])
            ui, Li = None, None
        
        if Li is not None and not region.inside(ui.reshape((1,-1))):
            # region was updated and we are not inside anymore 
            # so reset
            ui, Li = None, None
        
        if Li is None:
            self.startup(region, us, Ls)
        if self.sampler is None:
            self.start_direction(region)
        
        self.stepper.prepare_jump()
        Llast = None
        gaps = {}
        while True:
            if not self.sampler.is_done():
                u, is_independent = self.sampler.next(Llast=Llast)
                if not is_independent:
                    # should evaluate point
                    Llast = None
                    if region.inside(u.reshape((1,-1))):
                        p = transform(u)
                        L = loglike(p)
                        self.ncalls += 1
                        if L > Lmin:
                            Llast = L
                    else:
                        Llast = None
            else:
                u, i = self.stepper.check_gaps(gaps)
                if u is None:
                    unew, Lnew = self.stepper.make_jump(gaps)
                    break # done!
                # check that u is allowed:
                assert i not in gaps
                gaps[i] = True
                if region.inside(u.reshape((1,-1))):
                    p = transform(u)
                    L = loglike(p)
                    self.ncalls += 1
                    if L > Lmin:
                        # point is OK
                        gaps[i] = False
                        unew, Lnew = u, L
                        break
        
        #if self.log: print("after %d calls, jumped to" % self.ncalls, unew)
        assert np.isfinite(unew).all(), unew
        assert np.isfinite(Lnew).all(), Lnew
        
        self.accumulate_statistics()
        # forget sampler
        self.last = unew, Lnew
        self.sampler = None
        self.stepper = None
        # done, reset:
        #print("got a sample:", unew)
        if self.nrestarts >= self.nnewdirections:
            xnew = transform(unew)
            self.adjust_scale(maxlength = len(unew)**0.5)
            # forget as starting point
            self.last = None, None
            self.nrestarts = 0
            return unew, xnew, Lnew, self.ncalls
        else:
            return None, None, None, 0
    
    def plot(self, filename):
        if len(self.logstat) == 0:
            return
        
        parts = np.transpose(self.logstat)
        plt.figure(figsize=(10, 1+3*len(parts)))
        for i, (label, part) in enumerate(zip(self.logstat_labels, parts)):
            plt.subplot(len(parts), 1, 1+i)
            plt.ylabel(label)
            plt.plot(part)
            if np.min(part) > 0:
                plt.yscale('log')
        plt.savefig(filename, bbox_inches='tight')
        plt.close()
    
